"""Workplace policies: attendance, breaks and dress code KPIs, exceptions and observations."""

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import (
    AttendanceDay,
    ConductObservation,
    EmployeeProfile,
    MistakeRule,
    OrgUnit,
    PolicyVersion,
    WorkplaceException,
)
from app.models.workplace import DRESS_ITEMS, EXCEPTION_ACTIONS, EXCEPTION_REASONS
from app.pipeline.catalogue import WORKPLACE_POLICIES
from app.services import audit, rules_engine, settings_store, workforce, workplace
from app.services.rbac import Scope, descendants
from app.services.scoping import employee_in_scope, unit_ref

router = APIRouter(prefix="/api/workplace", tags=["workplace"])

VIEW = "workplace.view"
Days = Query(30, ge=7, le=180)


def _today() -> date:
    return utcnow().date()


def _scope(db: Session, principal: Principal, permission: str = VIEW) -> Scope:
    scope = principal.scope(db, permission)
    if scope.empty:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this resource")
    return scope


def policies(db: Session) -> list[dict]:
    rows = db.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.policy_code.in_(WORKPLACE_POLICIES), PolicyVersion.status == "active")
        .order_by(PolicyVersion.policy_code)
    )
    return [
        {
            "id": p.id,
            "code": p.policy_code,
            "version": p.version,
            "title": p.title,
            "title_ar": p.title_ar,
            "summary": p.summary,
            "summary_ar": p.summary_ar,
        }
        for p in rows
    ]


def _settings(db: Session) -> dict:
    return {
        "grace_minutes": settings_store.get(db, "workplace.grace_minutes"),
        "break_allowance_minutes": settings_store.get(db, "workplace.break_allowance_minutes"),
    }


def _focus(
    db: Session, principal: Principal, scope: Scope, unit_id: str | None
) -> tuple[OrgUnit, dict[str, OrgUnit], dict[str, list[str]]]:
    units, chains = workforce.unit_chain(db)
    if unit_id:
        unit = units.get(unit_id)
        if unit is None or not (scope.all or unit_id in scope.org_unit_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
        return unit, units, chains
    if scope.org_unit_ids and not scope.all:
        roots = [units[u] for u in scope.org_unit_ids if units[u].parent_id not in scope.org_unit_ids]
        return sorted(roots, key=lambda u: u.code)[0], units, chains
    if not scope.all and principal.employee_id:  # own record only
        return units[db.get(EmployeeProfile, principal.employee_id).org_unit_id], units, chains
    return next(u for u in units.values() if u.unit_type == "bank"), units, chains


def _overview(db: Session, scope: Scope, focus: OrgUnit, units, chains, days: int) -> dict:
    win = workplace.window(days, _today())
    leaves = descendants(db, {focus.id})
    if not scope.all and scope.org_unit_ids:
        leaves &= scope.org_unit_ids
    # Self scope (and the whole bank) need no unit filter: the scope itself narrows the data.
    narrowed = None if (scope.all and focus.unit_type == "bank") or not (scope.all or scope.org_unit_ids) else leaves
    children = {}
    for child in sorted((u for u in units.values() if u.parent_id == focus.id), key=lambda u: u.code):
        covered = descendants(db, {child.id}) & leaves
        if covered:
            children[child.id] = covered
    breakdown = workplace.unit_breakdown(db, scope, win, children) if children else {}
    series = workplace.daily_series(db, scope, win, narrowed)
    return {
        "generated_at": utcnow().isoformat(),
        "days": days,
        "since": win.since.isoformat(),
        "unit": unit_ref(focus),
        "breadcrumb": [unit_ref(units[u]) for u in reversed(chains.get(focus.id, []))],
        "kpis": workplace.kpis(db, scope, win, unit_ids=narrowed),
        "children": [
            {"unit": unit_ref(units[c]), "kpis": breakdown[c]} for c in children if breakdown[c]["scheduled_days"]
        ],
        "weekly": workplace.weekly(series),
        "weekday": workplace.weekday_pattern(series),
        "by_rule": workplace.by_rule(db, scope, win, narrowed),
        "reasons": workplace.reasons(db, scope, win, narrowed),
        "attention": workplace.attention_list(db, scope, win, narrowed),
        "settings": _settings(db),
        "policies": policies(db),
    }


@router.get("/overview")
def overview(
    unit_id: str | None = None,
    days: int = Days,
    principal: Principal = Depends(require(VIEW)),
    db: Session = Depends(get_db),
):
    scope = _scope(db, principal)
    focus, units, chains = _focus(db, principal, scope, unit_id)
    return _overview(db, scope, focus, units, chains, days)


# ------------------------------------------------------------------ exceptions
def _serialise(db: Session, rows: list[WorkplaceException], principal: Principal) -> list[dict]:
    if not rows:
        return []
    rules = {r.id: r for r in db.scalars(select(MistakeRule).where(MistakeRule.id.in_({x.rule_id for x in rows})))}
    profiles = {
        p.id: p
        for p in db.scalars(select(EmployeeProfile).where(EmployeeProfile.id.in_({x.employee_id for x in rows})))
    }
    units = {u.id: u for u in db.scalars(select(OrgUnit).where(OrgUnit.id.in_({x.org_unit_id for x in rows})))}
    att_ids = [x.source_id for x in rows if x.source_type == "attendance"]
    obs_ids = [x.source_id for x in rows if x.source_type == "conduct"]
    days = {d.id: d for d in db.scalars(select(AttendanceDay).where(AttendanceDay.id.in_(att_ids)))} if att_ids else {}
    obs = (
        {o.id: o for o in db.scalars(select(ConductObservation).where(ConductObservation.id.in_(obs_ids)))}
        if obs_ids
        else {}
    )
    review_scope = principal.scope(db, "workplace.review") if principal.has("workplace.review") else Scope()
    people = workforce.people(db, {x.responded_by for x in rows} | {x.decided_by for x in rows})
    out = []
    for x in rows:
        rule = rules.get(x.rule_id)
        p = profiles.get(x.employee_id)
        u = units.get(x.org_unit_id)
        own = principal.employee_id == x.employee_id
        if x.source_type == "attendance" and x.source_id in days:
            d = days[x.source_id]
            record = {
                "type": "attendance",
                "status": d.status,
                "scheduled": f"{workplace.clock(d.scheduled_start_min)}-{workplace.clock(d.scheduled_end_min)}",
                "check_in": workplace.clock(d.check_in_min),
                "check_out": workplace.clock(d.check_out_min),
                "minutes_late": d.minutes_late,
                "early_leave_minutes": d.early_leave_minutes,
                "break_minutes": d.break_minutes,
                "break_overrun_minutes": d.break_overrun_minutes,
            }
        elif x.source_id in obs:
            o = obs[x.source_id]
            record = {
                "type": "conduct",
                "item": o.item,
                "compliant": o.compliant,
                "observed_at": o.observed_at.isoformat(),
            }
        else:
            record = None
        out.append(
            {
                "id": x.id,
                "occurred_on": x.occurred_on.isoformat(),
                "status": x.status,
                "severity": x.severity,
                "rule": {
                    "id": rule.id,
                    "code": rule.rule_code,
                    "name": rule.name,
                    "name_ar": rule.name_ar,
                    "category": rule.category,
                    "expected": rule.expected_action,
                    "expected_ar": rule.expected_action_ar,
                }
                if rule
                else None,
                "employee": {"id": p.id, "pseudonym": p.pseudonym, "role_title": p.role_title} if p else None,
                "unit": {"id": u.id, "name": u.name, "name_ar": u.name_ar} if u else None,
                "matched": rules_engine.describe(x.matched_conditions),
                "record": record,
                "reason_code": x.reason_code,
                "reason_text": x.reason_text,
                "responded_at": x.responded_at.isoformat() if x.responded_at else None,
                "responded_by": people.get(x.responded_by),
                "decided_at": x.decided_at.isoformat() if x.decided_at else None,
                "decided_by": people.get(x.decided_by),
                "decision_note": x.decision_note,
                "action": x.action,
                "can_respond": own and principal.has("workplace.respond") and x.status == "open",
                "can_decide": not own
                and x.status in ("open", "explained")
                and (review_scope.all or x.org_unit_id in review_scope.org_unit_ids),
            }
        )
    return out


@router.get("/exceptions")
def list_exceptions(
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    rule_code: str | None = None,
    unit_id: str | None = None,
    employee_id: str | None = None,
    days: int = Query(90, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require(VIEW)),
    db: Session = Depends(get_db),
):
    scope = _scope(db, principal)
    cond = and_(
        workplace.scope_condition(scope, WorkplaceException.org_unit_id, WorkplaceException.employee_id),
        WorkplaceException.occurred_on >= _today() - timedelta(days=days),
    )
    stmt = select(WorkplaceException).join(MistakeRule, MistakeRule.id == WorkplaceException.rule_id)
    if status_filter == "pending":
        cond = and_(cond, WorkplaceException.status.in_(("open", "explained")))
    elif status_filter:
        cond = and_(cond, WorkplaceException.status == status_filter)
    if category:
        cond = and_(cond, MistakeRule.category == category)
    if rule_code:
        cond = and_(cond, MistakeRule.rule_code == rule_code)
    if unit_id:
        cond = and_(cond, WorkplaceException.org_unit_id.in_(descendants(db, {unit_id})))
    if employee_id:
        cond = and_(cond, WorkplaceException.employee_id == employee_id)
    total = db.scalar(select(func.count()).select_from(stmt.where(cond).subquery()))
    rows = list(
        db.scalars(
            stmt.where(cond)
            .order_by(WorkplaceException.occurred_on.desc(), WorkplaceException.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {"total": total, "page": page, "page_size": page_size, "items": _serialise(db, rows, principal)}


class RespondBody(BaseModel):
    reason_code: Literal[EXCEPTION_REASONS]  # type: ignore[valid-type]
    reason_text: str | None = Field(default=None, max_length=500)


@router.post("/exceptions/{exception_id}/respond")
def respond(
    exception_id: str,
    body: RespondBody,
    principal: Principal = Depends(require("workplace.respond")),
    db: Session = Depends(get_db),
):
    x = db.get(WorkplaceException, exception_id)
    if x is None or x.employee_id != principal.employee_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found")
    if x.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "This exception has already been explained or decided")
    x.status, x.reason_code = "explained", body.reason_code
    x.reason_text = (body.reason_text or "").strip() or None
    x.responded_by, x.responded_at = principal.user.id, utcnow()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="workplace.exception.explained",
        resource_type="workplace_exception",
        resource_id=x.id,
        request_id=principal.request_id,
        metadata={"reason_code": body.reason_code},
    )
    db.commit()
    return _serialise(db, [x], principal)[0]


class DecideBody(BaseModel):
    decision: Literal["excused", "confirmed", "dismissed"]
    action: Literal[EXCEPTION_ACTIONS] | None = None  # type: ignore[valid-type]
    note: str | None = Field(default=None, max_length=500)


def _decide(db: Session, principal: Principal, x: WorkplaceException, body: DecideBody, scope: Scope) -> None:
    if not (scope.all or x.org_unit_id in scope.org_unit_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found")
    if x.employee_id == principal.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot decide your own exception")
    if x.status not in ("open", "explained"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This exception has already been decided")
    x.status = body.decision
    x.action = body.action if body.decision == "confirmed" else None
    x.decision_note = (body.note or "").strip() or None
    x.decided_by, x.decided_at = principal.user.id, utcnow()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action=f"workplace.exception.{body.decision}",
        resource_type="workplace_exception",
        resource_id=x.id,
        request_id=principal.request_id,
        metadata={"action": x.action},
    )


@router.post("/exceptions/{exception_id}/decide")
def decide(
    exception_id: str,
    body: DecideBody,
    principal: Principal = Depends(require("workplace.review")),
    db: Session = Depends(get_db),
):
    x = db.get(WorkplaceException, exception_id)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exception not found")
    _decide(db, principal, x, body, principal.scope(db, "workplace.review"))
    db.commit()
    return _serialise(db, [x], principal)[0]


class BulkDecideBody(DecideBody):
    ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/exceptions/decide-bulk")
def decide_bulk(
    body: BulkDecideBody, principal: Principal = Depends(require("workplace.review")), db: Session = Depends(get_db)
):
    """Decide many exceptions at once (for example a time-clock fault that hit a whole branch)."""
    scope = principal.scope(db, "workplace.review")
    rows = list(db.scalars(select(WorkplaceException).where(WorkplaceException.id.in_(set(body.ids)))))
    decided, skipped = 0, []
    for x in rows:
        try:
            _decide(db, principal, x, body, scope)
            decided += 1
        except HTTPException as exc:
            skipped.append({"id": x.id, "reason": exc.status_code})
    skipped += [{"id": i, "reason": 404} for i in set(body.ids) - {x.id for x in rows}]
    db.commit()
    return {"decided": decided, "skipped": skipped}


# ---------------------------------------------------------------- observations
class ObservationBody(BaseModel):
    employee_id: str
    item: Literal[DRESS_ITEMS]  # type: ignore[valid-type]
    compliant: bool
    note: str | None = Field(default=None, max_length=300)


@router.post("/observations", status_code=status.HTTP_201_CREATED)
def observe(
    body: ObservationBody, principal: Principal = Depends(require("workplace.observe")), db: Session = Depends(get_db)
):
    employee = db.get(EmployeeProfile, body.employee_id)
    if employee is None or not employee_in_scope(principal.scope(db, "workplace.observe"), employee):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    if employee.id == principal.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot record an observation about yourself")
    obs, raised = workplace.record_observation(
        db, employee, body.item, body.compliant, (body.note or "").strip() or None, principal.user.id, utcnow()
    )
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="workplace.observation.recorded",
        resource_type="conduct_observation",
        resource_id=obs.id,
        request_id=principal.request_id,
        metadata={"item": body.item, "compliant": body.compliant, "exceptions": len(raised)},
    )
    db.commit()
    return {"id": obs.id, "exceptions": _serialise(db, raised, principal)}


@router.get("/employees")
def employees(
    q: str | None = Query(None, max_length=40),
    unit_id: str | None = None,
    principal: Principal = Depends(require("workplace.observe", "workplace.review")),
    db: Session = Depends(get_db),
):
    """Employees a supervisor may observe (for the observation form)."""
    permission = "workplace.observe" if principal.has("workplace.observe") else "workplace.review"
    scope = _scope(db, principal, permission)
    cond = workplace.scope_condition(scope, EmployeeProfile.org_unit_id, EmployeeProfile.id)
    if unit_id:
        cond = and_(cond, EmployeeProfile.org_unit_id.in_(descendants(db, {unit_id})))
    if q:
        cond = and_(cond, EmployeeProfile.pseudonym.ilike(f"%{q.strip()}%"))
    rows = db.scalars(select(EmployeeProfile).where(cond).order_by(EmployeeProfile.pseudonym).limit(50))
    return [
        {"id": e.id, "pseudonym": e.pseudonym, "role_title": e.role_title}
        for e in rows
        if e.id != principal.employee_id
    ]


# -------------------------------------------------------------------- employee
def employee_detail(db: Session, principal: Principal, employee: EmployeeProfile, days: int) -> dict:
    today = _today()
    win = workplace.window(days, today)
    scope = Scope(employee_ids={employee.id})
    recent = db.scalars(
        select(AttendanceDay)
        .where(AttendanceDay.employee_id == employee.id, AttendanceDay.work_date >= today - timedelta(days=30))
        .order_by(AttendanceDay.work_date.desc())
    )
    exceptions = list(
        db.scalars(
            select(WorkplaceException)
            .where(WorkplaceException.employee_id == employee.id, WorkplaceException.occurred_on >= win.since)
            .order_by(WorkplaceException.occurred_on.desc())
        )
    )
    observations = db.scalars(
        select(ConductObservation)
        .where(ConductObservation.employee_id == employee.id, ConductObservation.observed_at >= win.start_dt)
        .order_by(ConductObservation.observed_at.desc())
    )
    unit = db.get(OrgUnit, employee.org_unit_id)
    series = workplace.daily_series(db, scope, win)
    return {
        "employee": {
            "id": employee.id,
            "pseudonym": employee.pseudonym,
            "role_title": employee.role_title,
            "unit": unit_ref(unit),
            "schedule": f"{workplace.clock(employee.work_start_min)}-{workplace.clock(employee.work_end_min)}",
            "customer_facing": employee.customer_facing,
        },
        "days": days,
        "kpis": workplace.kpis(db, scope, win),
        "weekly": workplace.weekly(series),
        "recent_days": [
            {
                "date": d.work_date.isoformat(),
                "status": d.status,
                "check_in": workplace.clock(d.check_in_min),
                "check_out": workplace.clock(d.check_out_min),
                "minutes_late": d.minutes_late,
                "early_leave_minutes": d.early_leave_minutes,
                "break_minutes": d.break_minutes,
                "break_overrun_minutes": d.break_overrun_minutes,
                "worked_minutes": d.worked_minutes,
            }
            for d in recent
        ],
        "exceptions": _serialise(db, exceptions, principal),
        "observations": [
            {"id": o.id, "item": o.item, "compliant": o.compliant, "observed_at": o.observed_at.isoformat()}
            for o in observations
        ],
        "settings": _settings(db),
        "policies": policies(db),
    }


@router.get("/employees/{employee_id}")
def employee_view(
    employee_id: str,
    days: int = Query(90, ge=7, le=365),
    principal: Principal = Depends(require(VIEW)),
    db: Session = Depends(get_db),
):
    employee = db.get(EmployeeProfile, employee_id)
    if employee is None or not employee_in_scope(_scope(db, principal), employee):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return employee_detail(db, principal, employee, days)


@router.get("/me")
def my_record(
    days: int = Query(90, ge=7, le=365), principal: Principal = Depends(require(VIEW)), db: Session = Depends(get_db)
):
    employee = db.get(EmployeeProfile, principal.employee_id) if principal.employee_id else None
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No employee record is linked to this account")
    return employee_detail(db, principal, employee, days)
