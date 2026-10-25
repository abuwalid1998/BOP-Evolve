"""Employee learning profiles and versioned G0 → Gx history."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import (
    CoachingSession,
    EmployeeProfile,
    Finding,
    LearningGeneration,
    MistakeRule,
    OrgUnit,
    ServiceCase,
)
from app.services import audit, learning
from app.services.rbac import descendants
from app.services.scoping import employee_condition, employee_in_scope, org_path, unit_ref

router = APIRouter(prefix="/api", tags=["learning"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _generation_dict(g: LearningGeneration) -> dict:
    return {
        "id": g.id,
        "version": g.version,
        "generation_code": g.generation_code,
        "status": g.status,
        "effective_at": _iso(g.effective_at),
        "end_at": _iso(g.end_at),
        "score": g.score,
        "coverage": g.coverage,
        "evidence_count": g.evidence_count,
        "method_version": g.method_version,
        "approved_at": _iso(g.approved_at),
        "indicator_snapshot": g.indicator_snapshot,
    }


def _employee_or_404(db: Session, principal: Principal, employee_id: str, permission: str) -> EmployeeProfile:
    employee = db.get(EmployeeProfile, employee_id)
    if employee is None or not employee_in_scope(principal.scope(db, permission), employee):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return employee


@router.get("/employees")
def list_employees(
    org_unit: str | None = None,
    q: str | None = Query(None, max_length=40),
    principal: Principal = Depends(require("learning.view")),
    db: Session = Depends(get_db),
):
    scope = principal.scope(db, "learning.view")
    stmt = (
        select(EmployeeProfile, OrgUnit)
        .join(OrgUnit, OrgUnit.id == EmployeeProfile.org_unit_id)
        .where(employee_condition(scope))
    )
    if org_unit:
        stmt = stmt.where(EmployeeProfile.org_unit_id.in_(descendants(db, {org_unit})))
    if q:
        stmt = stmt.where(EmployeeProfile.pseudonym.ilike(f"%{q.strip()}%"))
    rows = db.execute(stmt.order_by(EmployeeProfile.pseudonym)).all()
    ids = [e.id for e, _ in rows]
    if not ids:
        return []

    generations: dict[str, dict] = {}
    for g in db.scalars(
        select(LearningGeneration)
        .where(LearningGeneration.employee_id.in_(ids), LearningGeneration.status != "rejected")
        .order_by(LearningGeneration.version)
    ):
        slot = generations.setdefault(g.employee_id, {"current": None, "pending": None})
        if g.status == "approved":
            slot["current"] = g
        elif g.status == "proposed":
            slot["pending"] = g

    counts = db.execute(
        select(ServiceCase.employee_id, Finding.status, func.count())
        .join(Finding, Finding.case_id == ServiceCase.id)
        .where(ServiceCase.employee_id.in_(ids))
        .group_by(ServiceCase.employee_id, Finding.status)
    ).all()
    by_emp: dict[str, dict] = {}
    for emp_id, st, n in counts:
        by_emp.setdefault(emp_id, {})[st] = n

    result = []
    for e, unit in rows:
        slot = generations.get(e.id, {})
        current, pending = slot.get("current"), slot.get("pending")
        c = by_emp.get(e.id, {})
        result.append(
            {
                "id": e.id,
                "pseudonym": e.pseudonym,
                "role_title": e.role_title,
                "org_unit": unit_ref(unit),
                "current_generation": current.generation_code if current else None,
                "current_score": current.score if current else None,
                "current_coverage": current.coverage if current else None,
                "pending_generation": pending.generation_code if pending else None,
                "confirmed": c.get("CONFIRMED", 0) + c.get("AMENDED", 0),
                "disputed": c.get("DISPUTED", 0),
                "pending_review": c.get("POTENTIAL", 0),
                "dismissed": c.get("DISMISSED", 0),
            }
        )
    return result


@router.get("/employees/{employee_id}/learning-history")
def learning_history(
    employee_id: str,
    principal: Principal = Depends(require("learning.view")),
    db: Session = Depends(get_db),
):
    employee = _employee_or_404(db, principal, employee_id, "learning.view")
    versions = db.scalars(
        select(LearningGeneration)
        .where(LearningGeneration.employee_id == employee.id)
        .order_by(LearningGeneration.version)
    ).all()
    evidence = learning.load_evidence(db, employee.id)
    live = learning.evaluate(evidence)

    rules = {r.id: r for r in db.scalars(select(MistakeRule))}
    case_by_id = {c.id: c for c in evidence.cases}
    timeline: list[dict] = []
    for f in evidence.findings:
        timeline.append(
            {
                "type": "finding",
                "at": _iso(f.created_at),
                "id": f.id,
                "case_id": f.case_id,
                "status": f.status,
                "category": rules[f.rule_id].category,
                "severity": f.severity,
            }
        )
    for r in evidence.responses:
        timeline.append(
            {
                "type": "response",
                "at": _iso(r.submitted_at),
                "id": r.id,
                "finding_id": r.finding_id,
                "stage": r.stage,
                "awareness_state": r.awareness_state,
                "understood": r.understood_after_feedback,
            }
        )
    for a in evidence.actions:
        if a.completed_at:
            timeline.append(
                {
                    "type": "action_completed",
                    "at": _iso(a.completed_at),
                    "id": a.id,
                    "finding_id": a.finding_id,
                    "action_type": a.action_type,
                }
            )
    for t in evidence.training:
        if t.completed_at:
            timeline.append(
                {
                    "type": "training",
                    "at": _iso(t.completed_at),
                    "id": t.id,
                    "course_code": t.course_code,
                    "score": t.score,
                }
            )
    for c in evidence.coaching:
        timeline.append(
            {
                "type": "coaching",
                "at": _iso(c.session_at),
                "id": c.id,
                "outcome": c.outcome_code,
                "reflection": c.reflection,
            }
        )
    for g in versions:
        timeline.append(
            {
                "type": "generation",
                "at": _iso(g.effective_at),
                "id": g.id,
                "code": g.generation_code,
                "status": g.status,
                "version": g.version,
            }
        )
    timeline.sort(key=lambda item: item["at"], reverse=True)

    categories: dict[str, dict] = {}
    for f in evidence.findings:
        cat = rules[f.rule_id].category
        slot = categories.setdefault(cat, {"confirmed": 0, "disputed": 0, "dismissed": 0, "pending": 0, "cases": 0})
        key = {
            "CONFIRMED": "confirmed",
            "AMENDED": "confirmed",
            "DISPUTED": "disputed",
            "DISMISSED": "dismissed",
            "POTENTIAL": "pending",
        }[f.status]
        slot[key] += 1
    for c in evidence.cases:
        categories.setdefault(c.case_type, {"confirmed": 0, "disputed": 0, "dismissed": 0, "pending": 0, "cases": 0})
        categories[c.case_type]["cases"] += 1

    open_actions = [
        {
            "id": a.id,
            "action_type": a.action_type,
            "description": a.description,
            "status": a.status,
            "due_at": _iso(a.due_at),
            "overdue": a.due_at < utcnow(),
            "finding_id": a.finding_id,
            "case_id": next((f.case_id for f in evidence.findings if f.id == a.finding_id), None),
        }
        for a in evidence.actions
        if a.status in ("planned", "in_progress")
    ]

    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="learning.view",
        resource_type="employee",
        resource_id=employee.id,
        request_id=principal.request_id,
    )
    db.commit()
    approved = [g for g in versions if g.status == "approved"]
    pending = [g for g in versions if g.status == "proposed"]
    return {
        "employee": {
            "id": employee.id,
            "pseudonym": employee.pseudonym,
            "role_title": employee.role_title,
            "start_date": employee.start_date.isoformat(),
            "org_path": [unit_ref(u) for u in org_path(db, employee.org_unit_id)],
        },
        "current": _generation_dict(approved[-1]) if approved else None,
        "pending": _generation_dict(pending[-1]) if pending else None,
        "versions": [_generation_dict(g) for g in versions],
        "live_evaluation": {
            "generation_code": live.generation_code,
            "score": live.score,
            "coverage": live.coverage,
            "evidence_count": live.evidence_count,
            **live.snapshot(utcnow()),
        },
        "case_count": len(case_by_id),
        "categories": categories,
        "open_actions": open_actions,
        "timeline": timeline[:150],
        "viewer": {
            "is_self": principal.employee_id == employee.id,
            "can_approve": principal.has("learning.approve") and principal.employee_id != employee.id,
            "can_record_coaching": principal.has("coaching.record") and principal.employee_id != employee.id,
        },
    }


@router.post("/employees/{employee_id}/learning-generations/evaluate")
def evaluate_generation(
    employee_id: str,
    principal: Principal = Depends(require("learning.approve", "coaching.record")),
    db: Session = Depends(get_db),
):
    perm = "learning.approve" if principal.has("learning.approve") else "coaching.record"
    employee = _employee_or_404(db, principal, employee_id, perm)
    generation = learning.refresh_generation(db, employee.id)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="learning.evaluate",
        resource_type="employee",
        resource_id=employee.id,
        request_id=principal.request_id,
        metadata={"new_version": generation.version if generation else None},
    )
    db.commit()
    return {"created": generation is not None, "generation": _generation_dict(generation) if generation else None}


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=500)


@router.post("/learning-generations/{generation_id}/decision")
def decide_generation(
    generation_id: str,
    body: DecisionBody,
    principal: Principal = Depends(require("learning.approve")),
    db: Session = Depends(get_db),
):
    generation = db.get(LearningGeneration, generation_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation not found")
    employee = _employee_or_404(db, principal, generation.employee_id, "learning.approve")
    if principal.employee_id == employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot approve your own learning profile")
    if generation.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only proposed versions can be decided")
    if body.decision == "approve":
        learning.approve(db, generation, principal.user.id)
    else:
        generation.status = "rejected"
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action=f"learning.{body.decision}",
        resource_type="learning_generation",
        resource_id=generation.id,
        request_id=principal.request_id,
        metadata={"employee_id": employee.id, "code": generation.generation_code},
    )
    db.commit()
    return _generation_dict(generation)


class CoachingBody(BaseModel):
    outcome_code: Literal["discussed", "practiced", "demonstrated", "needs_follow_up"]
    related_finding_id: str | None = None
    reflection: str | None = Field(None, max_length=1000)


@router.post("/employees/{employee_id}/coaching-sessions", status_code=201)
def record_coaching(
    employee_id: str,
    body: CoachingBody,
    principal: Principal = Depends(require("coaching.record")),
    db: Session = Depends(get_db),
):
    employee = _employee_or_404(db, principal, employee_id, "coaching.record")
    if principal.employee_id == employee.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot record coaching for yourself")
    if body.related_finding_id:
        finding = db.get(Finding, body.related_finding_id)
        case = db.get(ServiceCase, finding.case_id) if finding else None
        if case is None or case.employee_id != employee.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Finding does not belong to this employee")
    session = CoachingSession(
        employee_id=employee.id,
        manager_id=principal.user.id,
        related_finding_id=body.related_finding_id,
        session_at=utcnow(),
        outcome_code=body.outcome_code,
        reflection=body.reflection,
    )
    db.add(session)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="coaching.record",
        resource_type="coaching_session",
        resource_id=session.id,
        request_id=principal.request_id,
        metadata={"employee_id": employee.id},
    )
    learning.refresh_generation(db, employee.id)
    db.commit()
    return {"id": session.id}
