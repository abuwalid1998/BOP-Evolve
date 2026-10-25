"""Team / branch insights with privacy thresholds, plus aggregate scenario simulation."""

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import (
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    LearningGeneration,
    ModelRegistry,
    OrgUnit,
    ServiceCase,
    SimulationRun,
)
from app.pipeline.catalogue import CASE_TYPES
from app.services import audit, simulation
from app.services.rbac import descendants
from app.services.scoping import case_condition, unit_ref

router = APIRouter(prefix="/api", tags=["insights"])

_GEN_RANK = {"G0": 0, "G1": 1, "G2": 2, "G3": 3, "G4": 4, "G5": 5}


@router.get("/insights/teams")
def team_insights(
    level: Literal["department", "region", "branch", "section"] = "branch",
    days: int = Query(90, ge=14, le=365),
    principal: Principal = Depends(require("insights.view")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    scope = principal.scope(db, "insights.view")
    since = utcnow() - timedelta(days=days)
    units = {u.id: u for u in db.scalars(select(OrgUnit))}

    def ancestor_at_level(unit_id: str) -> OrgUnit | None:
        current = units.get(unit_id)
        while current is not None and current.unit_type != level:
            current = units.get(current.parent_id) if current.parent_id else None
        return current

    cases = db.execute(
        select(ServiceCase.id, ServiceCase.org_unit_id, ServiceCase.employee_id).where(
            case_condition(scope), ServiceCase.occurred_at >= since
        )
    ).all()
    findings = db.execute(
        select(Finding.id, Finding.case_id, Finding.status, Finding.contributing_factor)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(case_condition(scope), ServiceCase.occurred_at >= since)
    ).all()
    follow = dict(db.execute(select(FollowUpEvaluation.finding_id, FollowUpEvaluation.recurred)).all())
    actions = db.execute(
        select(ImprovementAction.finding_id, ImprovementAction.due_at, ImprovementAction.completed_at).where(
            ImprovementAction.status != "cancelled"
        )
    ).all()
    latest = (
        select(LearningGeneration.employee_id, func.max(LearningGeneration.version).label("v"))
        .where(LearningGeneration.status == "approved")
        .group_by(LearningGeneration.employee_id)
        .subquery()
    )
    generation_of = dict(
        db.execute(
            select(LearningGeneration.employee_id, LearningGeneration.generation_code).join(
                latest,
                (latest.c.employee_id == LearningGeneration.employee_id) & (latest.c.v == LearningGeneration.version),
            )
        ).all()
    )

    case_group: dict[str, str] = {}
    groups: dict[str, dict] = defaultdict(
        lambda: {
            "cases": 0,
            "employees": set(),
            "confirmed": 0,
            "disputed": 0,
            "dismissed": 0,
            "pending": 0,
            "factors": Counter(),
            "follow": [0, 0],
            "actions": [0, 0],
        }
    )
    for cid, unit_id, emp_id in cases:
        group = ancestor_at_level(unit_id)
        if group is None:
            continue
        case_group[cid] = group.id
        g = groups[group.id]
        g["cases"] += 1
        g["employees"].add(emp_id)
    findings_by_id = {}
    for fid, cid, st, factor in findings:
        gid = case_group.get(cid)
        if gid is None:
            continue
        findings_by_id[fid] = gid
        g = groups[gid]
        key = {
            "CONFIRMED": "confirmed",
            "AMENDED": "confirmed",
            "DISPUTED": "disputed",
            "DISMISSED": "dismissed",
            "POTENTIAL": "pending",
        }[st]
        g[key] += 1
        if key == "confirmed":
            g["factors"][factor] += 1
            if fid in follow:
                g["follow"][0] += 1
                g["follow"][1] += int(bool(follow[fid]))
    now = utcnow()
    for fid, due_at, completed_at in actions:
        gid = findings_by_id.get(fid)
        if gid is None or not (due_at <= now or completed_at):
            continue
        groups[gid]["actions"][0] += 1
        groups[gid]["actions"][1] += int(completed_at is not None)

    rows = []
    for gid, g in groups.items():
        unit = units[gid]
        n_emp = len(g["employees"])
        suppressed = n_emp < settings.privacy_min_group_employees or g["cases"] < settings.privacy_min_group_cases
        gens = [generation_of[e] for e in g["employees"] if e in generation_of]
        row = {"org_unit": unit_ref(unit), "suppressed": suppressed, "employees": n_emp if not suppressed else None}
        if not suppressed:
            confirmed = g["confirmed"]
            total_factors = sum(g["factors"].values())
            systemic = sum(g["factors"][k] for k in ("policy_ambiguity", "process_design", "system_issue"))
            row.update(
                {
                    "cases": g["cases"],
                    "confirmed": confirmed,
                    "disputed": g["disputed"],
                    "dismissed": g["dismissed"],
                    "pending": g["pending"],
                    "rate_per_100": round(100 * confirmed / g["cases"], 2) if g["cases"] else None,
                    "recurrence_rate": round(g["follow"][1] / g["follow"][0], 3) if g["follow"][0] else None,
                    "action_completion": round(g["actions"][1] / g["actions"][0], 3) if g["actions"][0] else None,
                    "systemic_share": round(systemic / total_factors, 3) if total_factors else None,
                    "factors": dict(g["factors"]),
                    "generation_mix": dict(Counter(gens)),
                    "avg_generation": round(sum(_GEN_RANK[c] for c in gens) / len(gens), 2) if gens else None,
                }
            )
        rows.append(row)
    rows.sort(key=lambda r: r["org_unit"]["code"])
    return {
        "level": level,
        "window_days": days,
        "privacy": {
            "min_employees": settings.privacy_min_group_employees,
            "min_cases": settings.privacy_min_group_cases,
        },
        "groups": rows,
        "note": "Raw counts are not comparable across groups without accounting for workload and case mix.",
    }


# -------------------------------------------------------------------- simulation
class SimulationBody(BaseModel):
    case_type: str
    interventions: list[Literal[tuple(simulation.INTERVENTIONS)]] = Field(min_length=1, max_length=6)  # type: ignore[valid-type]
    org_unit_id: str | None = None
    horizon_days: int = Field(90, ge=30, le=365)
    employee_id: str | None = None


@router.get("/simulations/options")
def simulation_options(principal: Principal = Depends(require("simulations.run"))):
    settings = get_settings()
    return {
        "case_types": list(CASE_TYPES),
        "interventions": [
            {"code": code, "reduction": spec["reduction"], "driver": spec["driver"]}
            for code, spec in simulation.INTERVENTIONS.items()
        ],
        "employee_level_enabled": settings.employee_level_simulation_enabled,
        "scenario_code": simulation.SCENARIO_CODE,
    }


@router.post("/simulations")
def run_simulation(
    body: SimulationBody,
    principal: Principal = Depends(require("simulations.run")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if body.employee_id and not settings.employee_level_simulation_enabled:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="simulation.run",
            resource_type="simulation",
            request_id=principal.request_id,
            outcome="denied",
            metadata={"reason": "employee_level_disabled"},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Employee-level estimates are disabled pending a separate approval and validation gate.",
        )
    if body.case_type not in CASE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown case type")

    scope = principal.scope(db, "simulations.run")
    org_ids: set[str] | None = None if scope.all else set(scope.org_unit_ids)
    if body.org_unit_id:
        requested = descendants(db, {body.org_unit_id})
        org_ids = requested if org_ids is None else requested & org_ids
        if not org_ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Org unit not found")
    elif org_ids is not None and not org_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organisational scope for simulation")

    result = simulation.run(
        db,
        case_type=body.case_type,
        interventions=list(body.interventions),
        org_unit_ids=org_ids,
        horizon_days=body.horizon_days,
    )
    model = db.scalar(select(ModelRegistry).where(ModelRegistry.name == "Recurrence scenario simulator"))
    if model is not None:
        result["model"] = {"name": model.name, "version": model.version, "status": model.status}
    run = SimulationRun(
        scenario_code=simulation.SCENARIO_CODE,
        model_id=model.id if model else None,
        created_by=principal.user.id,
        input_snapshot=body.model_dump(),
        output_summary=result,
        limitations=result["limitations"],
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="simulation.run",
        resource_type="simulation",
        resource_id=run.id,
        request_id=principal.request_id,
        metadata={"case_type": body.case_type},
    )
    db.commit()
    return {"id": run.id, "created_at": run.created_at.isoformat(), **result}


@router.get("/simulations")
def list_simulations(principal: Principal = Depends(require("simulations.run")), db: Session = Depends(get_db)):
    runs = db.scalars(
        select(SimulationRun)
        .where(SimulationRun.created_by == principal.user.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(20)
    ).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "input": r.input_snapshot,
            "best": (r.output_summary or {}).get("recommended_next_step"),
        }
        for r in runs
    ]
