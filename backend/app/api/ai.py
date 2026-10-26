"""Generative-assistant endpoints. Each builds a pseudonymised payload for one task.

Payloads carry employee reference codes, roles, dates, facts and statistics only: never
names, free-text comments written by staff, national IDs or customer data.
"""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.db import get_db, utcnow
from app.models import (
    EmployeeProfile,
    EmployeeResponse,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    MistakeRule,
    PolicyVersion,
    ReviewDecision,
    ServiceCase,
)
from app.pipeline.catalogue import FIELDS, OPERATORS, fields_for
from app.services import ai, rules_engine, workforce
from app.services.scoping import case_in_scope, employee_in_scope

router = APIRouter(prefix="/api/ai", tags=["ai"])

Lang = Literal["en", "ar"]


class GenerateBody(BaseModel):
    language: Lang = "en"
    refresh: bool = False


def _run(db: Session, principal: Principal, task: str, payload: dict, body: GenerateBody, **subject) -> dict:
    try:
        return ai.generate(
            db,
            task,
            payload,
            language=body.language,
            actor_id=principal.user.id,
            refresh=body.refresh,
            request_id=principal.request_id,
            **subject,
        )
    except ai.AIError as exc:
        code = {
            "disabled": status.HTTP_409_CONFLICT,
            "feature_disabled": status.HTTP_409_CONFLICT,
            "not_configured": status.HTTP_409_CONFLICT,
            "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
        }.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        raise HTTPException(code, {"code": exc.code, "message": exc.message}) from exc


@router.get("/status")
def ai_status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """What the UI may offer. No key material is returned."""
    s = ai.status(db)
    return {
        "available": s["enabled"] and s["configured"],
        "enabled": s["enabled"],
        "configured": s["configured"],
        "model": s["model"],
        "provider": s["provider"],
        "features": s["features"],
    }


# ------------------------------------------------------------ policy writing
class PolicyDraftBody(GenerateBody):
    notes: str = Field(min_length=10, max_length=3000)
    policy_code: str | None = Field(default=None, max_length=40)
    current_title: str | None = Field(default=None, max_length=200)
    current_summary: str | None = Field(default=None, max_length=4000)


@router.post("/policy-draft")
def policy_draft(
    body: PolicyDraftBody, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)
):
    payload = {
        "notes": body.notes.strip(),
        "policy_code": body.policy_code,
        "current_title": body.current_title,
        "current_requirement": body.current_summary,
        "organisation": "Bank of Palestine (retail and corporate bank, Palestine)",
    }
    return _run(db, principal, "policy_draft", payload, body, subject_type="policy_draft")


def _fact_catalogue(category: str) -> list[dict]:
    out = []
    for key in fields_for(category):
        f = FIELDS[key]
        out.append(
            {
                "key": key,
                "type": f["type"],
                "label": f["label"][0],
                "operators": [k for k, op in OPERATORS.items() if f["type"] in op["types"]],
                "options": [v for v, *_ in f.get("options", [])] or None,
                "unit": f["unit"][0] if "unit" in f else None,
                "min": f.get("min"),
                "max": f.get("max"),
            }
        )
    return out


class RuleDraftBody(GenerateBody):
    description: str = Field(min_length=10, max_length=2000)
    category: str
    policy_version_id: str | None = None


@router.post("/rule-draft")
def rule_draft(
    body: RuleDraftBody, principal: Principal = Depends(require("rules.author")), db: Session = Depends(get_db)
):
    if body.category not in rules_engine.all_types():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": {"category": "unknown_case_type"}})
    policy = db.get(PolicyVersion, body.policy_version_id) if body.policy_version_id else None
    payload = {
        "description": body.description.strip(),
        "service_type": body.category,
        "policy": {"code": policy.policy_code, "title": policy.title, "requirement": policy.summary}
        if policy
        else None,
        "available_facts": _fact_catalogue(body.category),
        "severities": ["low", "medium", "high", "critical"],
    }
    result = _run(db, principal, "rule_draft", payload, body, subject_type="rule_draft")
    output = dict(result["output"])
    # Never hand back conditions the engine would reject: validate them like any other rule.
    try:
        output["conditions"] = rules_engine.validate(body.category, output.get("conditions"))
        output["condition_errors"] = None
    except rules_engine.RuleError as exc:
        output["conditions"] = None
        output["condition_errors"] = exc.errors
    if output.get("severity") not in ("low", "medium", "high", "critical"):
        output["severity"] = "medium"
    if output.get("kind") not in ("breach", "early_warning"):
        output["kind"] = "breach"
    return {**result, "output": output}


class ExplainBody(GenerateBody):
    days: int = Field(default=90, ge=14, le=365)


@router.post("/rules/{rule_id}/explain-backtest")
def explain_backtest(
    rule_id: str,
    body: ExplainBody,
    principal: Principal = Depends(require("rules.view")),
    db: Session = Depends(get_db),
):
    rule = db.get(MistakeRule, rule_id)
    if rule is None or not rule.conditions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    active = db.scalar(
        select(MistakeRule).where(
            MistakeRule.rule_code == rule.rule_code, MistakeRule.status == "active", MistakeRule.id != rule.id
        )
    )
    result = rules_engine.backtest(
        db, rule.category, rule.conditions, days=body.days, compare=active.conditions if active else None
    )
    result.pop("samples", None)
    result["weekly"] = [w["matches"] for w in result["weekly"]]
    payload = {
        "rule": {
            "code": rule.rule_code,
            "version": rule.version,
            "status": rule.status,
            "kind": rule.kind,
            "service_type": rule.category,
            "name": rule.name,
            "conditions": [
                f"{d['label']} {d['op_label']} {d['value_label'] or ''}".strip()
                for d in rules_engine.describe(rule.conditions.get("conditions"))
            ],
            "match": rule.conditions.get("match"),
        },
        "compared_with": f"{active.rule_code} v{active.version} (in force)" if active else None,
        "backtest": result,
    }
    return _run(db, principal, "backtest_explain", payload, body, subject_type="rule", subject_id=rule.id)


# ------------------------------------------------------------ case assistant
@router.post("/findings/{finding_id}/assist")
def case_assist(
    finding_id: str,
    body: GenerateBody,
    principal: Principal = Depends(require("findings.review", "actions.manage", "workforce.view")),
    db: Session = Depends(get_db),
):
    finding = db.get(Finding, finding_id)
    case = db.get(ServiceCase, finding.case_id) if finding else None
    permission = next(p for p in ("findings.review", "actions.manage", "workforce.view") if principal.has(p))
    if case is None or not case_in_scope(principal.scope(db, permission), case):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    rule = db.get(MistakeRule, finding.rule_id)
    policy = db.get(PolicyVersion, rule.policy_version_id) if rule else None
    responses = db.scalars(select(EmployeeResponse).where(EmployeeResponse.finding_id == finding.id)).all()
    decisions = db.scalars(
        select(ReviewDecision).where(ReviewDecision.finding_id == finding.id).order_by(ReviewDecision.decided_at)
    ).all()
    actions = db.scalars(select(ImprovementAction).where(ImprovementAction.finding_id == finding.id)).all()
    follow_up = db.scalar(select(FollowUpEvaluation).where(FollowUpEvaluation.finding_id == finding.id))
    before = next((r for r in responses if r.stage == "before_feedback"), None)
    after = next((r for r in responses if r.stage == "after_feedback"), None)
    payload = {
        "service_type": case.case_type,
        "channel": case.interaction_type,
        "complexity": case.complexity_band,
        "occurred_on": case.occurred_at.date().isoformat(),
        "rule": {"code": rule.rule_code, "name": rule.name, "expected": rule.expected_action} if rule else None,
        "policy": {"code": policy.policy_code, "version": policy.version, "title": policy.title} if policy else None,
        "facts_that_met_the_rule": [
            f"{d['label']}: {d['actual_label']} (rule: {d['op_label']} {d['value_label'] or ''})".strip()
            for d in rules_engine.describe(finding.matched_conditions)
        ],
        "observed": finding.observed_action,
        "severity": finding.severity,
        "status": finding.status,
        "detection_confidence": finding.confidence,
        "employee_awareness_before_feedback": before.awareness_state if before else None,
        "employee_context_factors": before.contextual_factors if before else [],
        "understood_after_feedback": after.understood_after_feedback if after else None,
        "review_decisions": [{"decision": d.decision, "root_cause": d.contributing_factor} for d in decisions],
        "corrective_actions": [{"type": a.action_type, "status": a.status} for a in actions],
        "follow_up": {"comparable_cases": follow_up.comparable_cases, "repeats": follow_up.recurrences}
        if follow_up
        else None,
    }
    return _run(db, principal, "case_assistant", payload, body, subject_type="finding", subject_id=finding.id)


# ------------------------------------------------------- workplace insights
class InsightsBody(GenerateBody):
    unit_id: str | None = None
    days: int = Field(default=30, ge=7, le=180)


@router.post("/workplace/insights")
def workplace_insights(
    body: InsightsBody, principal: Principal = Depends(require("workplace.view")), db: Session = Depends(get_db)
):
    """Patterns, likely causes and recommendations for a unit's attendance, break and dress-code KPIs.

    Aggregates only: the list of individual employees is never sent.
    """
    from app.api.workplace import overview as workplace_overview

    if not (
        principal.has("workplace.review")
        or principal.scope(db, "workplace.view").org_unit_ids
        or principal.scope(db, "workplace.view").all
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unit-level insights are for managers and HR")
    data = workplace_overview(body.unit_id, body.days, principal, db)

    def slim(k: dict) -> dict:
        keep = (
            "employees",
            "days_worked",
            "punctuality_rate",
            "attendance_rate",
            "unapproved_absence_rate",
            "break_compliance_rate",
            "punch_completeness_rate",
            "avg_break_minutes",
            "avg_minutes_late_when_late",
            "lost_hours_per_employee_month",
            "dress_compliance_rate",
            "adherence_index",
        )
        out = {key: k[key] for key in keep}
        out["exceptions"] = {s: k["exceptions"][s] for s in ("confirmed", "excused", "dismissed", "awaiting_decision")}
        return out

    payload = {
        "unit": {"type": data["unit"]["type"], "name": data["unit"]["name"]},
        "period_days": body.days,
        "policy_settings": data["settings"],
        "kpis": slim(data["kpis"]),
        "sub_units": [
            {"name": c["unit"]["name"], "type": c["unit"]["type"], **slim(c["kpis"])} for c in data["children"][:25]
        ],
        "weekly_trend": data["weekly"],
        "late_arrivals_by_weekday": data["weekday"],
        "exceptions_by_rule": [
            {"rule": r["rule_code"], "name": r["name"], "total": r["total"], "by_status": r["by_status"]}
            for r in data["by_rule"]
        ],
        "reasons_given": data["reasons"],
        "policies": [{"code": p["code"], "title": p["title"], "requirement": p["summary"]} for p in data["policies"]],
    }
    return _run(
        db, principal, "workplace_insights", payload, body, subject_type="org_unit", subject_id=data["unit"]["id"]
    )


# ---------------------------------------------------------- employee summary
@router.post("/employees/{employee_id}/summary")
def employee_summary(
    employee_id: str,
    body: GenerateBody,
    principal: Principal = Depends(require("workforce.view")),
    db: Session = Depends(get_db),
):
    employee = db.get(EmployeeProfile, employee_id)
    if employee is None or not employee_in_scope(principal.scope(db, "workforce.view"), employee):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    now = utcnow()
    model = workforce.fit_model(db)
    bundle = workforce.load(db, [employee.id], now - timedelta(days=workforce.WINDOW_DAYS))
    summary = workforce.analyse(bundle, employee.id, model, workforce.active_policies(db), now)
    from app.services import workplace  # local import: workplace depends on this module's siblings

    payload = {
        "employee_ref": employee.pseudonym,
        "role": employee.role_title,
        "period": "last 12 months",
        "development_stage": summary["stage"],
        "proposed_stage": summary["pending_stage"],
        "cases_handled": summary["cases_12m"],
        "confirmed_findings": summary["confirmed_12m"],
        "confirmed_per_100_cases": summary["rate_per_100"],
        "repeats_within_90_days": summary["repeats"],
        "learning_from_findings_rate": summary["learning_rate"],
        "corrective_actions": summary["actions"],
        "knowledge_gaps": [
            {"service_type": g["case_type"], "gap": g["code"], "count": g["count"]} for g in summary["knowledge_gaps"]
        ],
        "outlook_next_90_days": [
            {
                "service_type": o["case_type"],
                "chance_of_repeat": o["probability"],
                "peer_chance": o["peer_probability"],
                "level": o["band"],
                "suggested_action": o["recommendation"],
            }
            for o in summary["outlook"]
        ],
        "workplace_kpis_90_days": workplace.employee_kpis(db, employee.id, days=90),
    }
    return _run(db, principal, "employee_summary", payload, body, subject_type="employee", subject_id=employee.id)
