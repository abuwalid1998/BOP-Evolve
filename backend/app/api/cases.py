"""Mistake explorer and the human review / employee response / action workflow."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import (
    EmployeeProfile,
    EmployeeResponse,
    EvidenceRef,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    MistakeRule,
    ModelRegistry,
    ModelRun,
    OrgUnit,
    PolicyVersion,
    ReviewDecision,
    ServiceCase,
    SourceSystem,
    User,
)
from app.models.cases import ACTION_TYPES, AWARENESS_STATES, CONTRIBUTING_FACTORS, SEVERITIES
from app.services import audit, learning
from app.services.rbac import descendants
from app.services.scoping import case_condition, case_in_scope, org_path, unit_ref

router = APIRouter(prefix="/api", tags=["cases"])

_DECISION_STATUS = {"confirm": "CONFIRMED", "amend": "AMENDED", "dispute_upheld": "DISMISSED", "dismiss": "DISMISSED"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _user_label(db: Session, user_id: str | None) -> dict | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return {"id": user.id, "name": user.display_name, "name_ar": user.display_name_ar} if user else None


# --------------------------------------------------------------------------- list
@router.get("/cases")
def list_cases(
    status_: str | None = Query(None, alias="status"),
    branch: str | None = Query(None, description="Org unit id at any level"),
    case_type: str | None = None,
    severity: str | None = None,
    q: str | None = Query(None, max_length=60),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(require("cases.view")),
    db: Session = Depends(get_db),
):
    scope = principal.scope(db, "cases.view")
    stmt = (
        select(Finding, ServiceCase, MistakeRule, EmployeeProfile, OrgUnit)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .join(MistakeRule, MistakeRule.id == Finding.rule_id)
        .join(EmployeeProfile, EmployeeProfile.id == ServiceCase.employee_id)
        .join(OrgUnit, OrgUnit.id == ServiceCase.org_unit_id)
        .where(case_condition(scope))
    )
    if status_:
        stmt = stmt.where(Finding.status.in_([s.strip().upper() for s in status_.split(",")]))
    if branch:
        stmt = stmt.where(ServiceCase.org_unit_id.in_(descendants(db, {branch})))
    if case_type:
        stmt = stmt.where(ServiceCase.case_type == case_type)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    if from_:
        stmt = stmt.where(ServiceCase.occurred_at >= from_)
    if to:
        stmt = stmt.where(ServiceCase.occurred_at <= to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(ServiceCase.id.ilike(like), Finding.id.ilike(like), EmployeeProfile.pseudonym.ilike(like))
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Finding.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "finding_id": f.id,
                "case_id": c.id,
                "occurred_at": _iso(c.occurred_at),
                "flagged_at": _iso(f.created_at),
                "case_type": c.case_type,
                "interaction_type": c.interaction_type,
                "status": f.status,
                "severity": f.severity,
                "rule_code": r.rule_code,
                "confidence": f.confidence,
                "detection_method": f.detection_method,
                "contributing_factor": f.contributing_factor,
                "employee": {"id": e.id, "pseudonym": e.pseudonym},
                "org_unit": unit_ref(u),
            }
            for f, c, r, e, u in rows
        ],
    }


# ------------------------------------------------------------------------- detail
def _load_case_for(db: Session, principal: Principal, case_id: str, permission: str) -> ServiceCase:
    case = db.get(ServiceCase, case_id)
    if case is None or not case_in_scope(principal.scope(db, permission), case):
        # Same response for "missing" and "out of scope" so existence is not disclosed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def _finding_detail(db: Session, principal: Principal, finding: Finding, can_restricted: bool) -> dict:
    rule = db.get(MistakeRule, finding.rule_id)
    policy = db.get(PolicyVersion, rule.policy_version_id)
    model = db.get(ModelRegistry, finding.model_id) if finding.model_id else None
    decisions = db.scalars(
        select(ReviewDecision).where(ReviewDecision.finding_id == finding.id).order_by(ReviewDecision.decided_at)
    ).all()
    responses = db.scalars(
        select(EmployeeResponse)
        .where(EmployeeResponse.finding_id == finding.id)
        .order_by(EmployeeResponse.submitted_at)
    ).all()
    actions = db.scalars(
        select(ImprovementAction)
        .where(ImprovementAction.finding_id == finding.id)
        .order_by(ImprovementAction.created_at)
    ).all()
    follow_up = db.scalar(select(FollowUpEvaluation).where(FollowUpEvaluation.finding_id == finding.id))
    now = utcnow()
    return {
        "id": finding.id,
        "status": finding.status,
        "severity": finding.severity,
        "reason_code": finding.reason_code,
        "explanation": finding.explanation,
        "explanation_ar": finding.explanation_ar,
        "observed_action": finding.observed_action,
        "observed_action_ar": finding.observed_action_ar,
        "detection_method": finding.detection_method,
        "confidence": finding.confidence,
        "contributing_factor": finding.contributing_factor,
        "created_at": _iso(finding.created_at),
        "reviewed_at": _iso(finding.reviewed_at),
        "reviewed_by": _user_label(db, finding.reviewed_by),
        "rule": {
            "id": rule.id,
            "code": rule.rule_code,
            "version": rule.version,
            "category": rule.category,
            "description": rule.description,
            "description_ar": rule.description_ar,
            "expected_action": rule.expected_action,
            "expected_action_ar": rule.expected_action_ar,
            "severity": rule.severity,
        },
        "policy": {
            "id": policy.id,
            "code": policy.policy_code,
            "version": policy.version,
            "title": policy.title,
            "title_ar": policy.title_ar,
            "effective_from": _iso(policy.effective_from),
            "effective_to": _iso(policy.effective_to),
        },
        "model": (
            {
                "id": model.id,
                "name": model.name,
                "version": model.version,
                "status": model.status,
                "limitations": model.limitations,
            }
            if model
            else None
        ),
        "decisions": [
            {
                "id": d.id,
                "decision": d.decision,
                "rationale": d.rationale,
                "policy_clear": d.policy_clear,
                "evidence_supports": d.evidence_supports,
                "system_issue_contributed": d.system_issue_contributed,
                "contributing_factor": d.contributing_factor,
                "amended_severity": d.amended_severity,
                "reviewer": _user_label(db, d.reviewer_id),
                "decided_at": _iso(d.decided_at),
            }
            for d in decisions
        ],
        "responses": [
            {
                "id": r.id,
                "stage": r.stage,
                "awareness_state": r.awareness_state,
                "understood_after_feedback": r.understood_after_feedback,
                "contextual_factors": r.contextual_factors or [],
                "response_text": r.response_text,
                "requested_review": r.requested_review,
                "submitted_at": _iso(r.submitted_at),
            }
            for r in responses
        ],
        "actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "description": a.description,
                "owner": _user_label(db, a.owner_id),
                "due_at": _iso(a.due_at),
                "status": a.status,
                "overdue": a.completed_at is None and a.status != "cancelled" and a.due_at < now,
                "completed_at": _iso(a.completed_at),
                "completion_evidence_ref": a.completion_evidence_ref,
            }
            for a in actions
        ],
        "follow_up": (
            {
                "window_days": follow_up.window_days,
                "comparable_cases": follow_up.comparable_cases,
                "recurrences": follow_up.recurrences,
                "recurred": follow_up.recurred,
                "evaluated_at": _iso(follow_up.evaluated_at),
            }
            if follow_up
            else None
        ),
        "can_review": principal.has("findings.review")
        and finding.status in ("POTENTIAL", "DISPUTED", "CONFIRMED", "AMENDED"),
        "can_restricted_evidence": can_restricted,
    }


@router.get("/cases/{case_id}")
def get_case(case_id: str, principal: Principal = Depends(require("cases.view")), db: Session = Depends(get_db)):
    case = _load_case_for(db, principal, case_id, "cases.view")
    employee = db.get(EmployeeProfile, case.employee_id)
    source = db.get(SourceSystem, case.source_system_id)
    can_restricted = principal.has("evidence.view_restricted")
    is_subject = principal.employee_id == case.employee_id

    evidence = []
    for ev in db.scalars(select(EvidenceRef).where(EvidenceRef.case_id == case.id)):
        visible = ev.access_class == "internal" or can_restricted
        evidence.append(
            {
                "id": ev.id,
                "type": ev.evidence_type,
                "access_class": ev.access_class,
                "secure_reference": ev.secure_reference if visible else None,
                "content_hash": ev.content_hash if visible else None,
                "summary": ev.summary if visible else None,
                "restricted": not visible,
            }
        )

    model_runs = [
        {
            "id": m.id,
            "model": db.get(ModelRegistry, m.model_id).name,
            "run_at": _iso(m.run_at),
            "output_summary": m.output_summary,
            "confidence": m.confidence,
            "latency_ms": m.latency_ms,
            "review_status": m.review_status,
        }
        for m in db.scalars(select(ModelRun).where(ModelRun.case_id == case.id))
    ]
    findings = db.scalars(select(Finding).where(Finding.case_id == case.id).order_by(Finding.created_at)).all()

    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="case.view",
        resource_type="service_case",
        resource_id=case.id,
        request_id=principal.request_id,
    )
    db.commit()
    return {
        "id": case.id,
        "source_case_key": case.source_case_key,
        "source_system": {"id": source.id, "code": source.code, "name": source.name},
        "occurred_at": _iso(case.occurred_at),
        "case_type": case.case_type,
        "interaction_type": case.interaction_type,
        "complexity_band": case.complexity_band,
        "data_quality_status": case.data_quality_status,
        "synthetic": case.is_synthetic,
        "employee": {"id": employee.id, "pseudonym": employee.pseudonym, "role_title": employee.role_title},
        "org_path": [unit_ref(u) for u in org_path(db, case.org_unit_id)],
        "evidence": evidence,
        "model_runs": model_runs,
        "findings": [_finding_detail(db, principal, f, can_restricted) for f in findings],
        "viewer": {
            "is_subject": is_subject,
            "can_respond": is_subject and principal.has("findings.respond"),
            "can_manage_actions": principal.has("actions.manage") and not is_subject,
        },
    }


# ----------------------------------------------------------------------- workflow
class ReviewBody(BaseModel):
    decision: Literal["confirm", "amend", "dispute_upheld", "dismiss"]
    rationale: str = Field(min_length=10, max_length=2000)
    policy_clear: bool | None = None
    evidence_supports: bool | None = None
    system_issue_contributed: bool | None = None
    contributing_factor: Literal[CONTRIBUTING_FACTORS] = "undetermined"  # type: ignore[valid-type]
    amended_severity: Literal[SEVERITIES] | None = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _amend_needs_severity(self):
        if self.decision == "amend" and not self.amended_severity:
            raise ValueError("amended_severity is required when decision is 'amend'")
        return self


def _finding_and_case(
    db: Session, principal: Principal, finding_id: str, permission: str
) -> tuple[Finding, ServiceCase]:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    case = _load_case_for(db, principal, finding.case_id, permission)
    return finding, case


@router.post("/findings/{finding_id}/review")
def review_finding(
    finding_id: str,
    body: ReviewBody,
    principal: Principal = Depends(require("findings.review")),
    db: Session = Depends(get_db),
):
    finding, case = _finding_and_case(db, principal, finding_id, "findings.review")
    if principal.employee_id and principal.employee_id == case.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot review a finding about yourself")
    if finding.status == "DISMISSED":
        raise HTTPException(status.HTTP_409_CONFLICT, "Finding already dismissed; a new finding is required")

    decision = ReviewDecision(
        finding_id=finding.id,
        decision=body.decision,
        rationale=body.rationale,
        policy_clear=body.policy_clear,
        evidence_supports=body.evidence_supports,
        system_issue_contributed=body.system_issue_contributed,
        contributing_factor=body.contributing_factor,
        amended_severity=body.amended_severity,
        reviewer_id=principal.user.id,
    )
    db.add(decision)
    previous = finding.status
    finding.status = _DECISION_STATUS[body.decision]
    finding.contributing_factor = body.contributing_factor
    finding.reviewed_by = principal.user.id
    finding.reviewed_at = decision.decided_at = utcnow()
    if body.amended_severity:
        finding.severity = body.amended_severity
    for run in db.scalars(select(ModelRun).where(ModelRun.case_id == case.id, ModelRun.review_status == "pending")):
        run.review_status = "overridden" if finding.status == "DISMISSED" else "accepted"
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="finding.review",
        resource_type="finding",
        resource_id=finding.id,
        request_id=principal.request_id,
        metadata={"from": previous, "to": finding.status, "decision": body.decision},
    )
    db.flush()
    learning.refresh_generation(db, case.employee_id)
    db.commit()
    return {"id": finding.id, "status": finding.status, "decision_id": decision.id}


class ResponseBody(BaseModel):
    stage: Literal["before_feedback", "after_feedback"]
    awareness_state: Literal[AWARENESS_STATES] | None = None  # type: ignore[valid-type]
    understood_after_feedback: bool | None = None
    contextual_factors: list[str] = Field(default_factory=list, max_length=8)
    response_text: str | None = Field(None, max_length=1000)
    requested_review: bool = False

    @model_validator(mode="after")
    def _stage_fields(self):
        if self.stage == "before_feedback" and self.awareness_state is None:
            raise ValueError("awareness_state is required before feedback")
        if self.stage == "after_feedback" and self.understood_after_feedback is None:
            raise ValueError("understood_after_feedback is required after feedback")
        return self


@router.post("/findings/{finding_id}/employee-response")
def employee_response(
    finding_id: str,
    body: ResponseBody,
    principal: Principal = Depends(require("findings.respond")),
    db: Session = Depends(get_db),
):
    finding, case = _finding_and_case(db, principal, finding_id, "cases.view")
    if principal.employee_id != case.employee_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the employee concerned can respond to this finding")
    if body.stage == "after_feedback":
        reviewed = db.scalar(
            select(func.count()).select_from(ReviewDecision).where(ReviewDecision.finding_id == finding.id)
        )
        if not reviewed:
            raise HTTPException(status.HTTP_409_CONFLICT, "Feedback has not been given yet for this finding")

    response = EmployeeResponse(
        finding_id=finding.id,
        stage=body.stage,
        awareness_state=body.awareness_state if body.stage == "before_feedback" else None,
        understood_after_feedback=body.understood_after_feedback if body.stage == "after_feedback" else None,
        contextual_factors=body.contextual_factors,
        response_text=body.response_text,
        requested_review=body.requested_review,
        submitted_by=principal.user.id,
    )
    db.add(response)
    if body.requested_review and finding.status in ("POTENTIAL", "CONFIRMED", "AMENDED"):
        finding.status = "DISPUTED"
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="finding.employee_response",
        resource_type="finding",
        resource_id=finding.id,
        request_id=principal.request_id,
        metadata={"stage": body.stage, "requested_review": body.requested_review},
    )
    db.flush()
    learning.refresh_generation(db, case.employee_id)
    db.commit()
    return {"id": response.id, "finding_status": finding.status}


class ActionBody(BaseModel):
    action_type: Literal[ACTION_TYPES]  # type: ignore[valid-type]
    description: str = Field(min_length=5, max_length=1000)
    owner_id: str | None = None
    due_at: datetime

    @model_validator(mode="after")
    def _future_due(self):
        if self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        if self.due_at < utcnow() - timedelta(minutes=5):
            raise ValueError("due_at must be in the future")
        return self


@router.post("/findings/{finding_id}/actions", status_code=201)
def create_action(
    finding_id: str,
    body: ActionBody,
    principal: Principal = Depends(require("actions.manage")),
    db: Session = Depends(get_db),
):
    finding, case = _finding_and_case(db, principal, finding_id, "actions.manage")
    if finding.status not in ("CONFIRMED", "AMENDED"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Actions can only be agreed for confirmed or amended findings")
    owner_id = body.owner_id or principal.user.id
    if db.get(User, owner_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown owner")
    action = ImprovementAction(
        finding_id=finding.id,
        action_type=body.action_type,
        description=body.description,
        owner_id=owner_id,
        due_at=body.due_at,
        created_by=principal.user.id,
    )
    db.add(action)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="action.create",
        resource_type="improvement_action",
        resource_id=action.id,
        request_id=principal.request_id,
        metadata={"finding_id": finding.id},
    )
    db.commit()
    return {"id": action.id}


class ActionPatch(BaseModel):
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = None
    completion_evidence_ref: str | None = Field(None, max_length=255)
    due_at: datetime | None = None


@router.patch("/actions/{action_id}")
def update_action(
    action_id: str,
    body: ActionPatch,
    principal: Principal = Depends(require("actions.manage", "actions.update_own")),
    db: Session = Depends(get_db),
):
    action = db.get(ImprovementAction, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    finding = db.get(Finding, action.finding_id)
    case = db.get(ServiceCase, finding.case_id)
    manages = principal.has("actions.manage") and case_in_scope(principal.scope(db, "actions.manage"), case)
    own = principal.has("actions.update_own") and (
        action.owner_id == principal.user.id or principal.employee_id == case.employee_id
    )
    if not (manages or own):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    if body.due_at is not None and not manages:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can change the due date")
    if action.status in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Completed or cancelled actions are immutable")

    changes = body.model_dump(exclude_none=True)
    if body.status == "completed":
        if not (body.completion_evidence_ref or action.completion_evidence_ref):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Completion evidence is required")
        action.completed_at = utcnow()
    if body.status == "cancelled" and not manages:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can cancel an action")
    for key, value in changes.items():
        setattr(action, key, value)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="action.update",
        resource_type="improvement_action",
        resource_id=action.id,
        request_id=principal.request_id,
        metadata={k: str(v) for k, v in changes.items()},
    )
    db.flush()
    learning.refresh_generation(db, case.employee_id)
    db.commit()
    return {"id": action.id, "status": action.status}


@router.get("/actions")
def list_actions(
    overdue: bool = False,
    mine: bool = False,
    principal: Principal = Depends(require("actions.manage", "actions.update_own", "cases.view")),
    db: Session = Depends(get_db),
):
    scope = principal.scope(db, "cases.view") if principal.has("cases.view") else principal.scope(db, "actions.manage")
    stmt = (
        select(ImprovementAction, Finding, ServiceCase, EmployeeProfile)
        .join(Finding, Finding.id == ImprovementAction.finding_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .join(EmployeeProfile, EmployeeProfile.id == ServiceCase.employee_id)
        .where(ImprovementAction.status.in_(("planned", "in_progress")))
    )
    if mine:
        stmt = stmt.where(ImprovementAction.owner_id == principal.user.id)
    else:
        stmt = stmt.where(case_condition(scope))
    if overdue:
        stmt = stmt.where(ImprovementAction.due_at < utcnow())
    rows = db.execute(stmt.order_by(ImprovementAction.due_at).limit(200)).all()
    now = utcnow()
    return [
        {
            "id": a.id,
            "action_type": a.action_type,
            "description": a.description,
            "status": a.status,
            "due_at": _iso(a.due_at),
            "overdue": a.due_at < now,
            "owner": _user_label(db, a.owner_id),
            "finding_id": f.id,
            "case_id": c.id,
            "employee": {"id": e.id, "pseudonym": e.pseudonym},
        }
        for a, f, c, e in rows
    ]
