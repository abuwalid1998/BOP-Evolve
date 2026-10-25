"""Chief HR Officer: workforce development by unit, and the printable employee report."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import EmployeeProfile, MistakeRule, OrgUnit
from app.services import audit, workforce
from app.services.scoping import employee_condition, employee_in_scope, unit_ref

router = APIRouter(prefix="/api/hr", tags=["hr"])

PERMISSION = "workforce.view"


def _iso(value):
    return value.isoformat() if value else None


def _stage_value(code: str | None) -> int | None:
    return workforce.STAGE_ORDER.get(code) if code else None


def _aggregate(rows: list[dict]) -> dict:
    cases = sum(r["cases_12m"] for r in rows)
    confirmed = sum(r["confirmed_12m"] for r in rows)
    stages = [_stage_value(r["stage"]) for r in rows if r["stage"]]
    evaluated = sum(r["follow_ups_evaluated"] for r in rows)
    learned = sum((r["learning_rate"] or 0) * r["follow_ups_evaluated"] for r in rows)
    return {
        "employees": len(rows),
        "cases_12m": cases,
        "confirmed_12m": confirmed,
        "rate_per_100": round(100 * confirmed / cases, 2) if cases else None,
        "repeats": sum(r["repeats"] for r in rows),
        "learning_rate": round(learned / evaluated, 3) if evaluated else None,
        "avg_stage": round(sum(stages) / len(stages), 1) if stages else None,
        "open_actions": sum(r["actions"]["open"] for r in rows),
        "overdue_actions": sum(r["actions"]["overdue"] for r in rows),
        "elevated_outlook": sum(1 for r in rows if r["top_outlook"] and r["top_outlook"]["band"] == "elevated"),
        "knowledge_gaps": sum(len(r["knowledge_gaps"]) for r in rows),
    }


@router.get("/workforce")
def workforce_view(
    unit_id: str | None = None,
    q: str | None = Query(None, max_length=40),
    principal: Principal = Depends(require(PERMISSION)),
    db: Session = Depends(get_db),
):
    """Employees in scope with their development picture, grouped by department / branch."""
    now = utcnow()
    scope = principal.scope(db, PERMISSION)
    employees = workforce.employees_in(db, employee_condition(scope))
    units, chains = workforce.unit_chain(db)
    if unit_id and unit_id not in units:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")

    model = workforce.fit_model(db)
    policies = workforce.active_policies(db)
    bundle = workforce.load(db, [e.id for e in employees], now - timedelta(days=workforce.WINDOW_DAYS))
    rows: dict[str, dict] = {}
    for e in employees:
        chain = chains.get(e.org_unit_id, [])
        rows[e.id] = {
            "id": e.id,
            "pseudonym": e.pseudonym,
            "role_title": e.role_title,
            "unit_ids": chain,
            "path": [unit_ref(units[u]) for u in reversed(chain) if units[u].unit_type != "bank"],
            **workforce.analyse(bundle, e.id, model, policies, now),
        }

    selected = units.get(unit_id) if unit_id else next((u for u in units.values() if u.unit_type == "bank"), None)
    in_unit = [r for r in rows.values() if not unit_id or unit_id in r["unit_ids"]]
    children = [u for u in units.values() if selected and u.parent_id == selected.id]
    child_rows = []
    for child in sorted(children, key=lambda u: u.code):
        members = [r for r in in_unit if child.id in r["unit_ids"]]
        if members:
            child_rows.append({"unit": unit_ref(child), **_aggregate(members)})
    breadcrumb = [unit_ref(units[u]) for u in reversed(chains.get(selected.id, []))] if selected else []
    if q:
        needle = q.strip().lower()
        in_unit = [r for r in in_unit if needle in r["pseudonym"].lower() or needle in r["role_title"].lower()]
    for r in in_unit:
        r.pop("unit_ids", None)
    return {
        "generated_at": now.isoformat(),
        "unit": unit_ref(selected),
        "breadcrumb": breadcrumb,
        "totals": _aggregate(in_unit),
        "children": child_rows,
        "employees": in_unit,
        "model": model.describe(workforce.registry(db)),
    }


def _employee_or_404(db: Session, principal: Principal, employee_id: str) -> EmployeeProfile:
    employee = db.get(EmployeeProfile, employee_id)
    if employee is None or not employee_in_scope(principal.scope(db, PERMISSION), employee):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return employee


@router.get("/employees/{employee_id}/report")
def employee_report(
    employee_id: str, principal: Principal = Depends(require(PERMISSION)), db: Session = Depends(get_db)
):
    """Everything the employee development report prints."""
    employee = _employee_or_404(db, principal, employee_id)
    now = utcnow()
    since = now - timedelta(days=workforce.WINDOW_DAYS)
    model = workforce.fit_model(db)
    bundle = workforce.load(db, [employee.id], since, detail=True)
    summary = workforce.analyse(bundle, employee.id, model, workforce.active_policies(db), now)
    units, chains = workforce.unit_chain(db)
    rules = {r.id: r for r in db.scalars(select(MistakeRule))}

    findings = sorted(
        bundle.findings.get(employee.id, []), key=lambda f: bundle.case_of[f.id].occurred_at, reverse=True
    )
    coaching_by_finding: dict[str, list] = {}
    for s in bundle.coaching.get(employee.id, []):
        coaching_by_finding.setdefault(s.related_finding_id, []).append(s)
    user_ids = {d.reviewer_id for f in findings for d in bundle.decisions.get(f.id, [])}
    user_ids |= {a.owner_id for f in findings for a in bundle.actions.get(f.id, [])}
    user_ids |= {a.created_by for f in findings for a in bundle.actions.get(f.id, [])}
    user_ids |= {s.manager_id for s in bundle.coaching.get(employee.id, [])}
    user_ids |= {g.approved_by for g in bundle.stages.get(employee.id, [])}
    who = workforce.people(db, user_ids)

    timeline = []
    for f in findings:
        case = bundle.case_of[f.id]
        rule = rules.get(f.rule_id)
        decision = (bundle.decisions.get(f.id) or [None])[-1]
        fu = bundle.follow_ups.get(f.id)
        timeline.append(
            {
                "finding_id": f.id,
                "case_id": case.id,
                "occurred_at": case.occurred_at.isoformat(),
                "case_type": case.case_type,
                "rule": {"code": rule.rule_code, "version": rule.version, "name": rule.name, "name_ar": rule.name_ar}
                if rule
                else None,
                "severity": f.severity,
                "status": f.status,
                "observed": f.observed_action,
                "observed_ar": f.observed_action_ar,
                "awareness": workforce._awareness(bundle, f),
                "understood": workforce._understood(bundle, f),
                "decision": {
                    "decision": decision.decision,
                    "by": who.get(decision.reviewer_id),
                    "at": decision.decided_at.isoformat(),
                    "factor": decision.contributing_factor,
                }
                if decision
                else None,
                "actions": [
                    {
                        "type": a.action_type,
                        "description": a.description,
                        "owner": who.get(a.owner_id),
                        "agreed_by": who.get(a.created_by),
                        "status": a.status,
                        "due_at": _iso(a.due_at),
                        "completed_at": _iso(a.completed_at),
                        "on_time": bool(a.completed_at and a.completed_at <= a.due_at),
                        "overdue": a.status not in ("completed", "cancelled") and a.due_at < now,
                    }
                    for a in sorted(bundle.actions.get(f.id, []), key=lambda a: a.due_at)
                ],
                "coaching": [
                    {"at": s.session_at.isoformat(), "outcome": s.outcome_code, "by": who.get(s.manager_id)}
                    for s in coaching_by_finding.get(f.id, [])
                ],
                "follow_up": {"comparable": fu.comparable_cases, "recurrences": fu.recurrences, "recurred": fu.recurred}
                if fu
                else None,
            }
        )

    # Monthly occurrence over the last twelve months.
    months = []
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for i in range(11, -1, -1):
        y, m = start.year, start.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        months.append(f"{y:04d}-{m:02d}")
    per_month = {k: {"month": k, "cases": 0, "confirmed": 0, "findings": 0} for k in months}
    for _, _, at in bundle.cases.get(employee.id, []):
        key = at.strftime("%Y-%m")
        if key in per_month:
            per_month[key]["cases"] += 1
    for f in findings:
        key = bundle.case_of[f.id].occurred_at.strftime("%Y-%m")
        if key in per_month:
            per_month[key]["findings"] += 1
            if f.status in workforce.CONFIRMED:
                per_month[key]["confirmed"] += 1

    by_type: dict[str, dict] = {}
    for _, ctype, _ in bundle.cases.get(employee.id, []):
        by_type.setdefault(ctype, {"case_type": ctype, "cases": 0, "findings": 0, "confirmed": 0, "last_at": None})
        by_type[ctype]["cases"] += 1
    for f in findings:
        row = by_type.setdefault(
            bundle.case_of[f.id].case_type,
            {"case_type": bundle.case_of[f.id].case_type, "cases": 0, "findings": 0, "confirmed": 0, "last_at": None},
        )
        row["findings"] += 1
        if f.status in workforce.CONFIRMED:
            row["confirmed"] += 1
            at = bundle.case_of[f.id].occurred_at.isoformat()
            row["last_at"] = max(row["last_at"] or at, at)
    for row in by_type.values():
        row["rate_per_100"] = round(100 * row["confirmed"] / row["cases"], 2) if row["cases"] else None
        fus = [
            bundle.follow_ups[f.id]
            for f in findings
            if f.id in bundle.follow_ups and bundle.case_of[f.id].case_type == row["case_type"]
        ]
        row["learning_rate"] = round(sum(1 for fu in fus if not fu.recurred) / len(fus), 3) if fus else None

    stages = [
        {
            "code": g.generation_code,
            "status": g.status,
            "effective_at": g.effective_at.isoformat(),
            "approved_by": who.get(g.approved_by),
            "score": g.score,
        }
        for g in bundle.stages.get(employee.id, [])
    ]
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="hr.report_viewed",
        resource_type="employee",
        resource_id=employee.id,
        request_id=principal.request_id,
    )
    db.commit()
    return {
        "generated_at": now.isoformat(),
        "generated_by": {"name": principal.user.display_name, "name_ar": principal.user.display_name_ar},
        "employee": {
            "id": employee.id,
            "pseudonym": employee.pseudonym,
            "role_title": employee.role_title,
            "start_date": employee.start_date.isoformat() if employee.start_date else None,
            "path": [
                unit_ref(units[u])
                for u in reversed(chains.get(employee.org_unit_id, []))
                if units[u].unit_type != "bank"
            ],
        },
        "summary": summary,
        "stages": stages,
        "timeline": timeline,
        "monthly": [per_month[k] for k in months],
        "by_type": sorted(by_type.values(), key=lambda r: r["confirmed"], reverse=True),
        "model": model.describe(workforce.registry(db)),
    }


@router.post("/employees/{employee_id}/report/printed")
def report_printed(
    employee_id: str, principal: Principal = Depends(require(PERMISSION)), db: Session = Depends(get_db)
):
    employee = _employee_or_404(db, principal, employee_id)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="hr.report_printed",
        resource_type="employee",
        resource_id=employee.id,
        request_id=principal.request_id,
    )
    db.commit()
    return {"recorded": True}


@router.get("/units")
def units(principal: Principal = Depends(require(PERMISSION)), db: Session = Depends(get_db)):
    return [{**unit_ref(u), "parent_id": u.parent_id} for u in db.scalars(select(OrgUnit).order_by(OrgUnit.code))]
