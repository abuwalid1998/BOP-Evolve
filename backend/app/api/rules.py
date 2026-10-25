"""Policies & control rules: register, authoring, four-eyes approval, backtesting and forecasting.

Every rule version and policy version moves draft -> pending_approval -> active and is
never edited after submission; a change is a new version. The approver must be a
different person from the author and the submitter. Only active ``breach`` rules raise
findings; ``early_warning`` rules are monitored and forecast without naming anyone.
"""

import re
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, new_id, utcnow
from app.models import Finding, MistakeRule, OrgUnit, PolicyVersion, User
from app.models.cases import RULE_KINDS, SEVERITIES
from app.pipeline.catalogue import CASE_TYPES, FIELDS, OPERATORS
from app.services import audit, rules_engine

router = APIRouter(prefix="/api/rules", tags=["rules"])

RULE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
POLICY_CODE = re.compile(r"^[A-Z][A-Z0-9-]{1,39}$")
OPEN_STATUSES = ("draft", "pending_approval")


def _iso(value):
    return value.isoformat() if value else None


def _users(db: Session, ids) -> dict[str, dict]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {
        u.id: {"id": u.id, "name": u.display_name, "name_ar": u.display_name_ar or u.display_name}
        for u in db.scalars(select(User).where(User.id.in_(ids)))
    }


def _unprocessable(errors: dict[str, str]) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": errors})


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _audit(db: Session, principal: Principal, action: str, resource_type: str, resource_id: str, **metadata):
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=principal.request_id,
        metadata=metadata,
    )


def _four_eyes_blocked(principal: Principal, item) -> bool:
    return principal.user.id in {item.created_by, item.submitted_by}


def _actions(principal: Principal, item, active_kind: str) -> list[str]:
    """What this principal may do next with a rule or policy version."""
    actions = []
    if item.status == "draft" and principal.has("rules.author"):
        actions += ["edit", "submit", "delete"]
    if item.status == "pending_approval" and principal.has("rules.approve") and not _four_eyes_blocked(principal, item):
        actions += ["approve", "reject"]
    if item.status == "active" and principal.has("rules.approve"):
        actions.append("retire")
    if item.status == "active" and principal.has("rules.author") and active_kind == "rule":
        actions.append("new_version")
    if item.status in ("active", "superseded") and principal.has("rules.author") and active_kind == "policy":
        actions.append("new_version")
    return actions


# ----------------------------------------------------------------- catalogue
@router.get("/catalogue")
def catalogue(principal: Principal = Depends(require("rules.view"))):
    """Fields, operators and options the condition builder offers."""
    return {
        "case_types": [
            {"code": code, "policy_code": spec["policy"][0], "default_rule": spec["rule"]}
            for code, spec in CASE_TYPES.items()
        ],
        "fields": [
            {
                "key": key,
                "type": f["type"],
                "label": f["label"][0],
                "label_ar": f["label"][1],
                "case_types": f["case_types"],
                "options": [{"value": v, "label": en, "label_ar": ar} for v, en, ar in f.get("options", [])],
                "unit": f["unit"][0] if "unit" in f else None,
                "unit_ar": f["unit"][1] if "unit" in f else None,
                "min": f.get("min"),
                "max": f.get("max"),
            }
            for key, f in FIELDS.items()
        ],
        "operators": [
            {"key": key, "types": list(op["types"]), "label": op["label"][0], "label_ar": op["label"][1]}
            for key, op in OPERATORS.items()
        ],
        "severities": list(SEVERITIES),
        "kinds": list(RULE_KINDS),
        "max_conditions": rules_engine.MAX_CONDITIONS,
    }


# ------------------------------------------------------------------ policies
def _policy_out(principal: Principal, p: PolicyVersion, users: dict, rules: list[MistakeRule]) -> dict:
    return {
        "id": p.id,
        "code": p.policy_code,
        "version": p.version,
        "title": p.title,
        "title_ar": p.title_ar,
        "summary": p.summary,
        "summary_ar": p.summary_ar,
        "status": p.status,
        "effective_from": _iso(p.effective_from),
        "effective_to": _iso(p.effective_to),
        "created_by": users.get(p.created_by),
        "created_at": _iso(p.created_at),
        "submitted_by": users.get(p.submitted_by),
        "submitted_at": _iso(p.submitted_at),
        "approved_by": users.get(p.approved_by),
        "approved_at": _iso(p.approved_at),
        "review_note": p.review_note,
        "rules": [
            {
                "id": r.id,
                "code": r.rule_code,
                "version": r.version,
                "status": r.status,
                "name": r.name,
                "name_ar": r.name_ar,
                "kind": r.kind,
            }
            for r in rules
        ],
        "actions": _actions(principal, p, "policy"),
    }


@router.get("/policies")
def list_policies(principal: Principal = Depends(require("rules.view")), db: Session = Depends(get_db)):
    policies = db.scalars(select(PolicyVersion).order_by(PolicyVersion.policy_code, PolicyVersion.version)).all()
    rules: dict[str, list] = {}
    for r in db.scalars(select(MistakeRule).order_by(MistakeRule.rule_code, MistakeRule.version)):
        rules.setdefault(r.policy_version_id, []).append(r)
    users = _users(db, [u for p in policies for u in (p.created_by, p.submitted_by, p.approved_by)])
    return [_policy_out(principal, p, users, rules.get(p.id, [])) for p in policies]


class PolicyBody(BaseModel):
    from_policy_id: str | None = None
    policy_code: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=3, max_length=200)
    title_ar: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10, max_length=4000)
    summary_ar: str = Field(min_length=10, max_length=4000)
    effective_from: date | None = None


def _next_policy_version(db: Session, code: str) -> str:
    versions = db.scalars(select(PolicyVersion.version).where(PolicyVersion.policy_code == code)).all()
    best = (1, -1)
    for v in versions:
        try:
            major, minor = (int(x) for x in v.split(".", 1))
        except ValueError:
            continue
        best = max(best, (major, minor))
    return f"{best[0]}.{best[1] + 1}"


def _effective(value: date | None) -> datetime:
    if value is None:
        return utcnow()
    return datetime.combine(value, time.min, tzinfo=UTC)


def _get_policy(db: Session, policy_id: str) -> PolicyVersion:
    policy = db.get(PolicyVersion, policy_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy version not found")
    return policy


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(
    body: PolicyBody, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)
):
    if body.from_policy_id:
        base = _get_policy(db, body.from_policy_id)
        code = base.policy_code
        owner_unit_id = base.owner_unit_id
    else:
        code = (body.policy_code or "").strip().upper()
        if not POLICY_CODE.match(code):
            raise _unprocessable({"policy_code": "invalid"})
        if db.scalar(select(PolicyVersion.id).where(PolicyVersion.policy_code == code)):
            raise _unprocessable({"policy_code": "exists"})
        owner_unit_id = db.scalar(select(OrgUnit.id).where(OrgUnit.code == "DEP-OPS"))
    if db.scalar(
        select(PolicyVersion.id).where(PolicyVersion.policy_code == code, PolicyVersion.status.in_(OPEN_STATUSES))
    ):
        raise _conflict("This policy already has a draft or a version awaiting approval")
    now = utcnow()
    version = _next_policy_version(db, code) if body.from_policy_id else "1.0"
    policy = PolicyVersion(
        id=new_id("POL"),
        policy_code=code,
        version=version,
        title=body.title.strip(),
        title_ar=body.title_ar.strip(),
        summary=body.summary.strip(),
        summary_ar=body.summary_ar.strip(),
        effective_from=_effective(body.effective_from),
        owner_unit_id=owner_unit_id,
        status="draft",
        created_by=principal.user.id,
        created_at=now,
    )
    db.add(policy)
    _audit(db, principal, "policy.draft_created", "policy_version", policy.id, code=code, version=version)
    db.commit()
    return _policy_out(principal, policy, _users(db, [principal.user.id]), [])


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: str,
    body: PolicyBody,
    principal: Principal = Depends(require("rules.author")),
    db: Session = Depends(get_db),
):
    policy = _get_policy(db, policy_id)
    if policy.status != "draft":
        raise _conflict("Only drafts can be edited; create a new version instead")
    policy.title, policy.title_ar = body.title.strip(), body.title_ar.strip()
    policy.summary, policy.summary_ar = body.summary.strip(), body.summary_ar.strip()
    policy.effective_from = _effective(body.effective_from)
    _audit(db, principal, "policy.draft_updated", "policy_version", policy.id)
    db.commit()
    users = _users(db, [policy.created_by, policy.submitted_by, policy.approved_by])
    return _policy_out(principal, policy, users, [])


class NoteBody(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def _required_note(body: NoteBody) -> str:
    note = (body.note or "").strip()
    if len(note) < 5:
        raise _unprocessable({"note": "required"})
    return note


@router.post("/policies/{policy_id}/submit")
def submit_policy(
    policy_id: str, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)
):
    policy = _get_policy(db, policy_id)
    if policy.status != "draft":
        raise _conflict("Only drafts can be submitted")
    policy.status, policy.submitted_by, policy.submitted_at = "pending_approval", principal.user.id, utcnow()
    _audit(db, principal, "policy.submitted", "policy_version", policy.id)
    db.commit()
    return {"id": policy.id, "status": policy.status}


@router.post("/policies/{policy_id}/approve")
def approve_policy(
    policy_id: str,
    body: NoteBody,
    principal: Principal = Depends(require("rules.approve")),
    db: Session = Depends(get_db),
):
    policy = _get_policy(db, policy_id)
    if policy.status != "pending_approval":
        raise _conflict("Only versions awaiting approval can be approved")
    if _four_eyes_blocked(principal, policy):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Four-eyes rule: you cannot approve a version you drafted or submitted"
        )
    now = utcnow()
    effective = max(policy.effective_from, now)
    previous = db.scalars(
        select(PolicyVersion).where(
            PolicyVersion.policy_code == policy.policy_code,
            PolicyVersion.status == "active",
            PolicyVersion.id != policy.id,
        )
    ).all()
    for old in previous:
        old.status, old.effective_to = "superseded", effective
    policy.status, policy.effective_from = "active", effective
    policy.approved_by, policy.approved_at = principal.user.id, now
    policy.review_note = (body.note or "").strip() or None
    to_review = []
    if previous:
        to_review = [
            {"id": r.id, "code": r.rule_code, "version": r.version}
            for r in db.scalars(
                select(MistakeRule).where(
                    MistakeRule.policy_version_id.in_([p.id for p in previous]), MistakeRule.status == "active"
                )
            )
        ]
    _audit(
        db,
        principal,
        "policy.approved",
        "policy_version",
        policy.id,
        superseded=[p.id for p in previous],
        rules_to_review=[r["id"] for r in to_review],
    )
    db.commit()
    return {"id": policy.id, "status": policy.status, "rules_to_review": to_review}


@router.post("/policies/{policy_id}/reject")
def reject_policy(
    policy_id: str,
    body: NoteBody,
    principal: Principal = Depends(require("rules.approve")),
    db: Session = Depends(get_db),
):
    policy = _get_policy(db, policy_id)
    note = _required_note(body)
    if policy.status != "pending_approval":
        raise _conflict("Only versions awaiting approval can be returned")
    if _four_eyes_blocked(principal, policy):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Four-eyes rule: ask another approver to review this version")
    policy.status, policy.review_note = "draft", note
    _audit(db, principal, "policy.returned", "policy_version", policy.id)
    db.commit()
    return {"id": policy.id, "status": policy.status}


# --------------------------------------------------------------------- rules
def _rule_stats(db: Session) -> dict[str, dict]:
    rows = db.execute(
        select(Finding.rule_id, Finding.status, func.count()).group_by(Finding.rule_id, Finding.status)
    ).all()
    stats: dict[str, dict] = {}
    for rule_id, finding_status, count in rows:
        s = stats.setdefault(rule_id, {"findings": 0, "confirmed": 0, "dismissed": 0, "pending": 0})
        s["findings"] += count
        if finding_status in rules_engine.CONFIRMED:
            s["confirmed"] += count
        elif finding_status == "DISMISSED":
            s["dismissed"] += count
        else:
            s["pending"] += count
    return stats


def _rule_out(principal: Principal, r: MistakeRule, policies: dict, users: dict, stats: dict) -> dict:
    policy = policies.get(r.policy_version_id)
    return {
        "id": r.id,
        "code": r.rule_code,
        "version": r.version,
        "category": r.category,
        "kind": r.kind,
        "name": r.name,
        "name_ar": r.name_ar,
        "description": r.description,
        "description_ar": r.description_ar,
        "expected_action": r.expected_action,
        "expected_action_ar": r.expected_action_ar,
        "observed_action": r.observed_action,
        "observed_action_ar": r.observed_action_ar,
        "severity": r.severity,
        "base_confidence": r.base_confidence,
        "conditions": r.conditions,
        "status": r.status,
        "policy": (
            {
                "id": policy.id,
                "code": policy.policy_code,
                "version": policy.version,
                "title": policy.title,
                "title_ar": policy.title_ar,
                "status": policy.status,
            }
            if policy
            else None
        ),
        "created_by": users.get(r.created_by),
        "created_at": _iso(r.created_at),
        "submitted_by": users.get(r.submitted_by),
        "submitted_at": _iso(r.submitted_at),
        "approved_by": users.get(r.approved_by),
        "approved_at": _iso(r.approved_at),
        "retired_at": _iso(r.retired_at),
        "review_note": r.review_note,
        "stats": stats.get(r.id, {"findings": 0, "confirmed": 0, "dismissed": 0, "pending": 0}),
        "actions": _actions(principal, r, "rule"),
        "four_eyes_blocked": r.status == "pending_approval" and _four_eyes_blocked(principal, r),
    }


def _get_rule(db: Session, rule_id: str) -> MistakeRule:
    rule = db.get(MistakeRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


@router.get("")
def list_rules(principal: Principal = Depends(require("rules.view")), db: Session = Depends(get_db)):
    rules = db.scalars(select(MistakeRule).order_by(MistakeRule.rule_code, MistakeRule.version)).all()
    policies = {p.id: p for p in db.scalars(select(PolicyVersion))}
    users = _users(db, [u for r in rules for u in (r.created_by, r.submitted_by, r.approved_by)])
    stats = _rule_stats(db)
    return [_rule_out(principal, r, policies, users, stats) for r in rules]


class RuleBody(BaseModel):
    from_rule_id: str | None = None
    rule_code: str | None = Field(default=None, max_length=40)
    category: str
    policy_version_id: str
    kind: str = "breach"
    name: str = Field(min_length=3, max_length=160)
    name_ar: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=2000)
    description_ar: str = Field(min_length=5, max_length=2000)
    expected_action: str = Field(min_length=5, max_length=2000)
    expected_action_ar: str = Field(min_length=5, max_length=2000)
    observed_action: str | None = Field(default=None, max_length=2000)
    observed_action_ar: str | None = Field(default=None, max_length=2000)
    severity: str
    base_confidence: float = Field(default=0.8, ge=0.05, le=0.99)
    conditions: dict


def _validated(db: Session, body: RuleBody) -> tuple[dict, PolicyVersion]:
    errors: dict[str, str] = {}
    if body.kind not in RULE_KINDS:
        errors["kind"] = "invalid"
    if body.severity not in SEVERITIES:
        errors["severity"] = "invalid"
    policy = db.get(PolicyVersion, body.policy_version_id)
    if policy is None or policy.status in ("superseded", "retired"):
        errors["policy_version_id"] = "invalid"
    try:
        conditions = rules_engine.validate(body.category, body.conditions)
    except rules_engine.RuleError as exc:
        errors.update(exc.errors)
        conditions = {}
    if errors:
        raise _unprocessable(errors)
    return conditions, policy


def _apply(rule: MistakeRule, body: RuleBody, conditions: dict) -> None:
    rule.category = body.category
    rule.policy_version_id = body.policy_version_id
    rule.kind = body.kind
    rule.name, rule.name_ar = body.name.strip(), body.name_ar.strip()
    rule.description, rule.description_ar = body.description.strip(), body.description_ar.strip()
    rule.expected_action, rule.expected_action_ar = body.expected_action.strip(), body.expected_action_ar.strip()
    rule.observed_action = (body.observed_action or "").strip() or None
    rule.observed_action_ar = (body.observed_action_ar or "").strip() or None
    rule.severity = body.severity
    rule.base_confidence = round(body.base_confidence, 2)
    rule.conditions = conditions


def _single_rule(db: Session, principal: Principal, rule: MistakeRule) -> dict:
    policies = {p.id: p for p in db.scalars(select(PolicyVersion).where(PolicyVersion.id == rule.policy_version_id))}
    users = _users(db, [rule.created_by, rule.submitted_by, rule.approved_by])
    return _rule_out(principal, rule, policies, users, _rule_stats(db))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleBody, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)):
    conditions, _ = _validated(db, body)
    if body.from_rule_id:
        base = _get_rule(db, body.from_rule_id)
        if base.category != body.category:
            raise _unprocessable({"category": "cannot_change"})
        code = base.rule_code
        versions = db.scalars(select(MistakeRule.version).where(MistakeRule.rule_code == code)).all()
        version = str(max((int(v) for v in versions if v.isdigit()), default=0) + 1)
    else:
        code = (body.rule_code or "").strip().upper()
        if not RULE_CODE.match(code):
            raise _unprocessable({"rule_code": "invalid"})
        if db.scalar(select(MistakeRule.id).where(MistakeRule.rule_code == code)):
            raise _unprocessable({"rule_code": "exists"})
        version = "1"
    if db.scalar(select(MistakeRule.id).where(MistakeRule.rule_code == code, MistakeRule.status.in_(OPEN_STATUSES))):
        raise _conflict("This rule already has a draft or a version awaiting approval")
    rule = MistakeRule(
        id=new_id("RUL"),
        rule_code=code,
        version=version,
        status="draft",
        created_by=principal.user.id,
        created_at=utcnow(),
    )
    _apply(rule, body, conditions)
    db.add(rule)
    _audit(db, principal, "rule.draft_created", "rule", rule.id, code=code, version=version)
    db.commit()
    return _single_rule(db, principal, rule)


@router.put("/{rule_id}")
def update_rule(
    rule_id: str,
    body: RuleBody,
    principal: Principal = Depends(require("rules.author")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, rule_id)
    if rule.status != "draft":
        raise _conflict("Only drafts can be edited; create a new version instead")
    if body.category != rule.category and rule.version != "1":
        raise _unprocessable({"category": "cannot_change"})
    conditions, _ = _validated(db, body)
    _apply(rule, body, conditions)
    _audit(db, principal, "rule.draft_updated", "rule", rule.id)
    db.commit()
    return _single_rule(db, principal, rule)


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_id)
    if rule.status != "draft":
        raise _conflict("Only drafts can be deleted")
    if db.scalar(select(Finding.id).where(Finding.rule_id == rule.id).limit(1)):
        raise _conflict("This draft is referenced by findings")
    _audit(db, principal, "rule.draft_deleted", "rule", rule.id, code=rule.rule_code, version=rule.version)
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


@router.post("/{rule_id}/submit")
def submit_rule(rule_id: str, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_id)
    if rule.status != "draft":
        raise _conflict("Only drafts can be submitted")
    rule.status, rule.submitted_by, rule.submitted_at = "pending_approval", principal.user.id, utcnow()
    _audit(db, principal, "rule.submitted", "rule", rule.id)
    db.commit()
    return _single_rule(db, principal, rule)


@router.post("/{rule_id}/approve")
def approve_rule(
    rule_id: str,
    body: NoteBody,
    principal: Principal = Depends(require("rules.approve")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, rule_id)
    if rule.status != "pending_approval":
        raise _conflict("Only versions awaiting approval can be approved")
    if _four_eyes_blocked(principal, rule):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Four-eyes rule: you cannot approve a rule you drafted or submitted"
        )
    policy = db.get(PolicyVersion, rule.policy_version_id)
    if policy is None or policy.status != "active":
        raise _conflict("The linked policy version must be approved and in force before this rule can go live")
    now = utcnow()
    replaced = db.scalars(
        select(MistakeRule).where(
            MistakeRule.rule_code == rule.rule_code, MistakeRule.status == "active", MistakeRule.id != rule.id
        )
    ).all()
    for old in replaced:
        old.status, old.retired_at = "retired", now
    rule.status, rule.approved_by, rule.approved_at = "active", principal.user.id, now
    rule.review_note = (body.note or "").strip() or None
    _audit(db, principal, "rule.approved", "rule", rule.id, replaced=[r.id for r in replaced])
    db.commit()
    return _single_rule(db, principal, rule)


@router.post("/{rule_id}/reject")
def reject_rule(
    rule_id: str,
    body: NoteBody,
    principal: Principal = Depends(require("rules.approve")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, rule_id)
    note = _required_note(body)
    if rule.status != "pending_approval":
        raise _conflict("Only versions awaiting approval can be returned")
    if _four_eyes_blocked(principal, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Four-eyes rule: ask another approver to review this rule")
    rule.status, rule.review_note = "draft", note
    _audit(db, principal, "rule.returned", "rule", rule.id)
    db.commit()
    return _single_rule(db, principal, rule)


@router.post("/{rule_id}/retire")
def retire_rule(
    rule_id: str,
    body: NoteBody,
    principal: Principal = Depends(require("rules.approve")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, rule_id)
    note = _required_note(body)
    if rule.status != "active":
        raise _conflict("Only active rules can be retired")
    rule.status, rule.retired_at, rule.review_note = "retired", utcnow(), note
    _audit(db, principal, "rule.retired", "rule", rule.id)
    db.commit()
    return _single_rule(db, principal, rule)


# ------------------------------------------------------------------ backtest
class BacktestBody(BaseModel):
    category: str
    conditions: dict
    days: int = Field(default=90, ge=14, le=365)
    compare_rule_id: str | None = None


def _run_backtest(db: Session, principal: Principal, category: str, conditions: dict, days: int, compare_rule_id):
    try:
        definition = rules_engine.validate(category, conditions)
    except rules_engine.RuleError as exc:
        raise _unprocessable(exc.errors) from exc
    compare = None
    compare_rule = None
    if compare_rule_id:
        compare_rule = _get_rule(db, compare_rule_id)
        compare = compare_rule.conditions
    scope = principal.scope(db, "cases.view") if principal.has("cases.view") else None
    result = rules_engine.backtest(db, category, definition, days=days, compare=compare, sample_scope=scope)
    if compare_rule is not None:
        result["comparison"]["rule"] = {
            "id": compare_rule.id,
            "code": compare_rule.rule_code,
            "version": compare_rule.version,
        }
    return result


@router.post("/backtest")
def backtest(body: BacktestBody, principal: Principal = Depends(require("rules.view")), db: Session = Depends(get_db)):
    return _run_backtest(db, principal, body.category, body.conditions, body.days, body.compare_rule_id)


@router.get("/{rule_id}/backtest")
def backtest_rule(
    rule_id: str,
    days: int = Query(default=90, ge=14, le=365),
    principal: Principal = Depends(require("rules.view")),
    db: Session = Depends(get_db),
):
    rule = _get_rule(db, rule_id)
    active = db.scalar(
        select(MistakeRule.id).where(
            MistakeRule.rule_code == rule.rule_code, MistakeRule.status == "active", MistakeRule.id != rule.id
        )
    )
    return _run_backtest(db, principal, rule.category, rule.conditions or {}, days, active)
