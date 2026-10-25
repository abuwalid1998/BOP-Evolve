"""Workforce development view for the Chief HR Officer.

Builds, for every employee in scope, the development picture HR needs: findings and
when they happened, what the manager or supervisor did about each one, whether the
learning held on later cases, open knowledge gaps, and an indicative repeat-risk
outlook per service type.

The outlook comes from the registered "Employee repeat-risk estimator", a Poisson-gamma
empirical-Bayes model fitted on the bank's own history (synthetic in the demo):

* a peer rate of confirmed findings per case for each service type;
* each employee's overall propensity relative to peers, pooled across all the service
  types they handle and shrunk towards 1 by a strength fitted (method of moments) from
  how much employees genuinely differ beyond chance;
* a per-service-type deviation from that propensity, shrunk towards it;
* learning multipliers estimated from follow-up results: did repeats happen less often
  when the corrective actions were completed, or when the employee confirmed understanding?
It is a statistical estimate for development planning, labelled as indicative, and is
never an input to disciplinary decisions.
"""

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    CoachingSession,
    EmployeeProfile,
    EmployeeResponse,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    LearningGeneration,
    MistakeRule,
    ModelRegistry,
    OrgUnit,
    PolicyVersion,
    ReviewDecision,
    Role,
    ServiceCase,
    TrainingRecord,
    User,
    UserRole,
)

MODEL_NAME = "Employee repeat-risk estimator"
WINDOW_DAYS = 365
HORIZON_DAYS = 90
CONFIRMED = {"CONFIRMED", "AMENDED"}
UNAWARE = {"not_recognized", "unsure"}
STAGE_ORDER = {"G0": 0, "G1": 1, "G2": 2, "G3": 3, "G4": 4, "G5": 5}
SYSTEMIC = {"policy_ambiguity", "process_design", "system_issue"}
_CACHE_SECONDS = 600
TYPE_STRENGTH = 3.0  # expected findings' worth of trust in the employee's overall propensity per type


# ------------------------------------------------------------------- the model
@dataclass
class RiskModel:
    fitted_at: datetime
    period_from: datetime
    period_to: datetime
    cases: int
    follow_ups: int
    peer_rate: dict[str, float]
    employee_strength: float  # prior strength for an employee's propensity, in expected findings
    type_strength: float  # prior strength for a service type's deviation from it
    multipliers: dict[str, float]

    def describe(self, registry: ModelRegistry | None) -> dict:
        return {
            "name": registry.name if registry else MODEL_NAME,
            "version": registry.version if registry else "1.0",
            "status": registry.status if registry else "MONITORING",
            "limitations": registry.limitations if registry else "",
            "fitted_at": self.fitted_at.isoformat(),
            "period_from": self.period_from.isoformat(),
            "period_to": self.period_to.isoformat(),
            "cases": self.cases,
            "follow_ups": self.follow_ups,
            "peer_rate": {k: round(v, 4) for k, v in self.peer_rate.items()},
            "employee_strength": round(self.employee_strength, 2),
            "type_strength": self.type_strength,
            "multipliers": {k: round(v, 2) for k, v in self.multipliers.items()},
            "horizon_days": HORIZON_DAYS,
        }


_model_cache: tuple[float, RiskModel] | None = None


def _ratio(group: list[bool], overall: float) -> float:
    if len(group) < 10 or overall <= 0:
        return 1.0
    return min(2.5, max(0.4, (sum(group) / len(group)) / overall))


def fit_model(db: Session, now: datetime | None = None) -> RiskModel:
    """Fit the estimator on the last year of history (cached for ten minutes)."""
    global _model_cache
    if _model_cache and time.monotonic() - _model_cache[0] < _CACHE_SECONDS and now is None:
        return _model_cache[1]
    now = now or utcnow()
    since = now - timedelta(days=WINDOW_DAYS)

    exposure: dict[tuple[str, str], int] = defaultdict(int)
    for emp, ctype in db.execute(
        select(ServiceCase.employee_id, ServiceCase.case_type).where(ServiceCase.occurred_at >= since)
    ):
        exposure[(emp, ctype)] += 1
    confirmed: dict[tuple[str, str], int] = defaultdict(int)
    for emp, ctype in db.execute(
        select(ServiceCase.employee_id, ServiceCase.case_type)
        .join(Finding, Finding.case_id == ServiceCase.id)
        .where(ServiceCase.occurred_at >= since, Finding.status.in_(CONFIRMED))
    ):
        confirmed[(emp, ctype)] += 1

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (_, ctype), n in exposure.items():
        totals[ctype][0] += n
    for (_, ctype), c in confirmed.items():
        totals[ctype][1] += c
    peer_rate = {ctype: (c / n if n else 0.0) for ctype, (n, c) in totals.items()}

    # Employee propensity: observed vs expected confirmed findings across all service types.
    observed: dict[str, int] = defaultdict(int)
    expected: dict[str, float] = defaultdict(float)
    for (emp, ctype), n in exposure.items():
        expected[emp] += n * peer_rate[ctype]
        observed[emp] += confirmed.get((emp, ctype), 0)
    keys = [e for e in expected if expected[e] >= 1]
    employee_strength = 10.0
    if len(keys) >= 5:
        ratios = [observed[e] / expected[e] for e in keys]
        mean = sum(ratios) / len(ratios)
        var = sum((r - mean) ** 2 for r in ratios) / (len(ratios) - 1)
        noise = sum(1 / expected[e] for e in keys) / len(keys)  # Poisson noise of each ratio
        tau2 = var - noise
        employee_strength = min(50.0, max(0.5, 1 / tau2)) if tau2 > 0 else 50.0

    # Learning multipliers from follow-up outcomes.
    rows = db.execute(
        select(FollowUpEvaluation.finding_id, FollowUpEvaluation.recurred, FollowUpEvaluation.evaluated_at)
    ).all()
    finding_ids = [r[0] for r in rows]
    actions: dict[str, list[ImprovementAction]] = defaultdict(list)
    understood: dict[str, bool] = {}
    if finding_ids:
        for a in db.scalars(select(ImprovementAction).where(ImprovementAction.finding_id.in_(finding_ids))):
            actions[a.finding_id].append(a)
        for r in db.scalars(
            select(EmployeeResponse).where(
                EmployeeResponse.finding_id.in_(finding_ids), EmployeeResponse.stage == "after_feedback"
            )
        ):
            understood[r.finding_id] = bool(r.understood_after_feedback)
    outcomes = [bool(r[1]) for r in rows]
    overall = sum(outcomes) / len(outcomes) if outcomes else 0.0
    done, not_done, und, not_und = [], [], [], []
    for fid, recurred, evaluated_at in rows:
        acts = actions.get(fid, [])
        complete = bool(acts) and all(a.completed_at and a.completed_at <= evaluated_at for a in acts)
        (done if complete else not_done).append(bool(recurred))
        (und if understood.get(fid) else not_und).append(bool(recurred))
    # Monotone constraint: learning evidence may only lower the estimate and its absence may only
    # raise it. An estimate pointing the other way is noise in a small sample, so it counts as 1.
    multipliers = {
        "actions_completed": min(1.0, _ratio(done, overall)),
        "actions_open": max(1.0, _ratio(not_done, overall)),
        "understood": min(1.0, _ratio(und, overall)),
        "not_understood": max(1.0, _ratio(not_und, overall)),
    }
    model = RiskModel(
        fitted_at=now,
        period_from=since,
        period_to=now,
        cases=sum(exposure.values()),
        follow_ups=len(rows),
        peer_rate=peer_rate,
        employee_strength=employee_strength,
        type_strength=TYPE_STRENGTH,
        multipliers=multipliers,
    )
    _model_cache = (time.monotonic(), model)
    return model


def band(probability: float, peer_probability: float) -> str:
    """Risk band relative to peers with the same caseload, so busy roles are not flagged for volume alone."""
    ratio = probability / peer_probability if peer_probability > 0 else 1.0
    if probability < 0.1 or ratio < 0.85:
        return "low"
    if ratio >= 1.5 and probability >= 0.15:
        return "elevated"
    return "moderate"


# ------------------------------------------------------------------ evidence
@dataclass
class Bundle:
    """Everything needed to describe a set of employees, loaded in a handful of queries."""

    cases: dict[str, list[tuple]] = field(default_factory=lambda: defaultdict(list))  # emp -> (id, type, at)
    findings: dict[str, list[Finding]] = field(default_factory=lambda: defaultdict(list))
    case_of: dict[str, ServiceCase] = field(default_factory=dict)
    decisions: dict[str, list[ReviewDecision]] = field(default_factory=lambda: defaultdict(list))
    responses: dict[str, list[EmployeeResponse]] = field(default_factory=lambda: defaultdict(list))
    actions: dict[str, list[ImprovementAction]] = field(default_factory=lambda: defaultdict(list))
    follow_ups: dict[str, FollowUpEvaluation] = field(default_factory=dict)
    training: dict[str, list[TrainingRecord]] = field(default_factory=lambda: defaultdict(list))
    coaching: dict[str, list[CoachingSession]] = field(default_factory=lambda: defaultdict(list))
    stages: dict[str, list[LearningGeneration]] = field(default_factory=lambda: defaultdict(list))


def load(db: Session, employee_ids: list[str], since: datetime, *, detail: bool = False) -> Bundle:
    b = Bundle()
    if not employee_ids:
        return b
    for cid, emp, ctype, at in db.execute(
        select(ServiceCase.id, ServiceCase.employee_id, ServiceCase.case_type, ServiceCase.occurred_at).where(
            ServiceCase.employee_id.in_(employee_ids), ServiceCase.occurred_at >= since
        )
    ):
        b.cases[emp].append((cid, ctype, at))
    rows = db.execute(
        select(Finding, ServiceCase)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(ServiceCase.employee_id.in_(employee_ids), ServiceCase.occurred_at >= since)
    ).all()
    for f, c in rows:
        b.findings[c.employee_id].append(f)
        b.case_of[f.id] = c
    fids = list(b.case_of)
    if fids:
        for model, target in ((EmployeeResponse, b.responses), (ImprovementAction, b.actions)):
            for item in db.scalars(select(model).where(model.finding_id.in_(fids))):
                target[item.finding_id].append(item)
        for fu in db.scalars(select(FollowUpEvaluation).where(FollowUpEvaluation.finding_id.in_(fids))):
            b.follow_ups[fu.finding_id] = fu
        if detail:
            for d in db.scalars(
                select(ReviewDecision).where(ReviewDecision.finding_id.in_(fids)).order_by(ReviewDecision.decided_at)
            ):
                b.decisions[d.finding_id].append(d)
    for t in db.scalars(select(TrainingRecord).where(TrainingRecord.employee_id.in_(employee_ids))):
        b.training[t.employee_id].append(t)
    for s in db.scalars(select(CoachingSession).where(CoachingSession.employee_id.in_(employee_ids))):
        b.coaching[s.employee_id].append(s)
    for g in db.scalars(
        select(LearningGeneration)
        .where(LearningGeneration.employee_id.in_(employee_ids), LearningGeneration.status != "rejected")
        .order_by(LearningGeneration.version)
    ):
        b.stages[g.employee_id].append(g)
    return b


def _occurred(b: Bundle, f: Finding) -> datetime:
    return b.case_of[f.id].occurred_at


def _type(b: Bundle, f: Finding) -> str:
    return b.case_of[f.id].case_type


def _understood(b: Bundle, f: Finding) -> bool | None:
    after = [r for r in b.responses.get(f.id, []) if r.stage == "after_feedback"]
    return after[-1].understood_after_feedback if after else None


def _awareness(b: Bundle, f: Finding) -> str | None:
    before = [r for r in b.responses.get(f.id, []) if r.stage == "before_feedback"]
    return before[-1].awareness_state if before else None


def _actions_complete(b: Bundle, f: Finding) -> bool:
    acts = b.actions.get(f.id, [])
    return bool(acts) and all(a.status == "completed" for a in acts)


# ------------------------------------------------------------------- analysis
def analyse(b: Bundle, emp_id: str, model: RiskModel, policies: dict[str, PolicyVersion], now: datetime) -> dict:
    """Summary figures, knowledge gaps and repeat-risk outlook for one employee."""
    cases = b.cases.get(emp_id, [])
    findings = sorted(b.findings.get(emp_id, []), key=lambda f: _occurred(b, f))
    confirmed = [f for f in findings if f.status in CONFIRMED]

    # Repeats: a confirmed finding preceded by another confirmed finding of the same type within 90 days.
    repeats = 0
    for i, f in enumerate(confirmed):
        if any(
            _type(b, g) == _type(b, f) and timedelta(0) < _occurred(b, f) - _occurred(b, g) <= timedelta(days=90)
            for g in confirmed[:i]
        ):
            repeats += 1

    evaluated = [b.follow_ups[f.id] for f in confirmed if f.id in b.follow_ups]
    learning_rate = sum(1 for fu in evaluated if not fu.recurred) / len(evaluated) if evaluated else None

    acts = [a for f in findings for a in b.actions.get(f.id, [])]
    completed = [a for a in acts if a.status == "completed"]
    on_time = [a for a in completed if a.completed_at and a.completed_at <= a.due_at]
    overdue = [a for a in acts if a.status not in ("completed", "cancelled") and a.due_at < now]
    open_actions = [a for a in acts if a.status in ("planned", "in_progress")]

    # Knowledge gaps per service type.
    gaps: list[dict] = []
    by_type: dict[str, list[Finding]] = defaultdict(list)
    for f in confirmed:
        by_type[_type(b, f)].append(f)
    learning_dates: dict[str, list[datetime]] = defaultdict(list)
    for s in b.coaching.get(emp_id, []):
        if s.related_finding_id in b.case_of:
            learning_dates[b.case_of[s.related_finding_id].case_type].append(s.session_at)
    for t in b.training.get(emp_id, []):
        if t.related_finding_id in b.case_of and t.completed_at:
            learning_dates[b.case_of[t.related_finding_id].case_type].append(t.completed_at)

    def gap(ctype: str, code: str, items: list[Finding]):
        if items:
            gaps.append(
                {
                    "case_type": ctype,
                    "code": code,
                    "count": len(items),
                    "last_at": max(_occurred(b, f) for f in items).isoformat(),
                }
            )

    for ctype, items in by_type.items():
        gap(ctype, "unaware_of_requirement", [f for f in items if _awareness(b, f) in UNAWARE])
        settled = [f for f in items if f.reviewed_at and now - f.reviewed_at > timedelta(days=14)]
        gap(ctype, "understanding_not_confirmed", [f for f in settled if _understood(b, f) is not True])
        dates = sorted(learning_dates.get(ctype, []))
        gap(ctype, "repeat_after_coaching", [f for f in items if dates and any(d < _occurred(b, f) for d in dates)])
        gap(
            ctype,
            "training_outstanding",
            [f for f in items if any(a.action_type == "training" and a.status != "completed" for a in b.actions[f.id])],
        )
        policy = policies.get(ctype)
        if policy and policy.effective_from and (not dates or dates[-1] < policy.effective_from):
            if any(_occurred(b, f) < policy.effective_from for f in items):
                gap(
                    ctype,
                    "policy_updated_since_learning",
                    [f for f in items if _occurred(b, f) < policy.effective_from],
                )

    # Outlook per service type the employee handles.
    recent = now - timedelta(days=HORIZON_DAYS)
    exposure: dict[str, int] = defaultdict(int)
    volume: dict[str, int] = defaultdict(int)
    for _, ctype, at in cases:
        exposure[ctype] += 1
        if at >= recent:
            volume[ctype] += 1
    expected_total = sum(n * model.peer_rate.get(ct, 0.0) for ct, n in exposure.items())
    propensity = (len(confirmed) + model.employee_strength) / (expected_total + model.employee_strength)
    outlook = []
    for ctype in sorted(set(exposure) | set(by_type)):
        n, c = exposure[ctype], len(by_type.get(ctype, []))
        prior = model.peer_rate.get(ctype, 0.0)
        expected_type = n * prior
        k = model.type_strength
        relative = (c + k * propensity) / (expected_type + k)
        rate = prior * relative
        mult = 1.0
        drivers: list[dict] = [{"code": "confirmed_12m", "n": c}]
        latest = by_type.get(ctype, [])[-1] if by_type.get(ctype) else None
        if latest:
            if _actions_complete(b, latest):
                mult *= model.multipliers["actions_completed"]
                drivers.append({"code": "actions_completed"})
            else:
                mult *= model.multipliers["actions_open"]
                drivers.append({"code": "actions_open"})
            understood = _understood(b, latest)
            if understood is True:
                mult *= model.multipliers["understood"]
                drivers.append({"code": "understood"})
            elif latest.reviewed_at and now - latest.reviewed_at > timedelta(days=14):
                mult *= model.multipliers["not_understood"]
                drivers.append({"code": "not_understood"})
        lam = volume[ctype] * rate * mult
        probability = 1 - math.exp(-lam)
        peer_probability = 1 - math.exp(-volume[ctype] * prior)
        if c:
            drivers.append({"code": "rate_vs_peers", "ratio": round(relative, 1)})
        drivers.append({"code": "volume", "n": volume[ctype]})
        type_gaps = {g["code"] for g in gaps if g["case_type"] == ctype}
        factors = [f.contributing_factor for f in by_type.get(ctype, [])]
        if "understanding_not_confirmed" in type_gaps or "unaware_of_requirement" in type_gaps:
            recommendation = "refresher_training"
        elif latest and not _actions_complete(b, latest):
            recommendation = "complete_actions"
        elif "repeat_after_coaching" in type_gaps:
            recommendation = "supervised_practice"
        elif "policy_updated_since_learning" in type_gaps:
            recommendation = "policy_briefing"
        elif factors and sum(1 for x in factors if x in SYSTEMIC) * 2 >= len(factors):
            recommendation = "process_review"
        else:
            recommendation = "monitor"
        outlook.append(
            {
                "case_type": ctype,
                "cases_12m": n,
                "confirmed_12m": c,
                "expected_cases": volume[ctype],
                "probability": round(probability, 3),
                "peer_probability": round(peer_probability, 3),
                "expected_repeats": round(lam, 2),
                "relative_risk": round(probability / peer_probability, 2) if peer_probability > 0 else None,
                "band": band(probability, peer_probability),
                "drivers": drivers,
                "recommendation": recommendation,
            }
        )
    rank = {"elevated": 2, "moderate": 1, "low": 0}
    outlook.sort(key=lambda o: (rank[o["band"]], o["probability"]), reverse=True)

    stages = b.stages.get(emp_id, [])
    approved = [g for g in stages if g.status == "approved"]
    pending = [g for g in stages if g.status == "proposed"]
    last = findings[-1] if findings else None
    return {
        "cases_12m": len(cases),
        "findings_12m": len(findings),
        "confirmed_12m": len(confirmed),
        "pending_review": sum(1 for f in findings if f.status == "POTENTIAL"),
        "under_objection": sum(1 for f in findings if f.status == "DISPUTED"),
        "dismissed": sum(1 for f in findings if f.status == "DISMISSED"),
        "rate_per_100": round(100 * len(confirmed) / len(cases), 2) if cases else None,
        "repeats": repeats,
        "learning_rate": round(learning_rate, 3) if learning_rate is not None else None,
        "follow_ups_evaluated": len(evaluated),
        "actions": {
            "total": len(acts),
            "completed": len(completed),
            "on_time": len(on_time),
            "open": len(open_actions),
            "overdue": len(overdue),
            "on_time_rate": round(len(on_time) / len(completed), 3) if completed else None,
        },
        "last_finding_at": _occurred(b, last).isoformat() if last else None,
        "stage": approved[-1].generation_code if approved else None,
        "stage_since": approved[-1].effective_at.isoformat() if approved else None,
        "pending_stage": pending[-1].generation_code if pending else None,
        "knowledge_gaps": gaps,
        "outlook": outlook,
        "top_outlook": outlook[0] if outlook else None,
        "propensity": round(propensity, 2),
    }


def active_policies(db: Session) -> dict[str, PolicyVersion]:
    """Policy version currently in force for each service type (via the active rules)."""
    out: dict[str, PolicyVersion] = {}
    for rule, policy in db.execute(
        select(MistakeRule, PolicyVersion)
        .join(PolicyVersion, PolicyVersion.id == MistakeRule.policy_version_id)
        .where(MistakeRule.status == "active", MistakeRule.kind == "breach")
    ):
        out.setdefault(rule.category, policy)
    return out


def people(db: Session, user_ids) -> dict[str, dict]:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    roles: dict[str, str] = {}
    for uid, code in db.execute(
        select(UserRole.user_id, Role.code).join(Role, Role.id == UserRole.role_id).where(UserRole.user_id.in_(ids))
    ):
        roles.setdefault(uid, code)
    return {
        u.id: {
            "id": u.id,
            "name": u.display_name,
            "name_ar": u.display_name_ar or u.display_name,
            "role": roles.get(u.id),
        }
        for u in db.scalars(select(User).where(User.id.in_(ids)))
    }


def unit_chain(db: Session) -> tuple[dict[str, OrgUnit], dict[str, list[str]]]:
    """All units, and for each unit the ids of itself and its ancestors."""
    units = {u.id: u for u in db.scalars(select(OrgUnit))}
    chains: dict[str, list[str]] = {}
    for uid in units:
        chain, cur = [], units.get(uid)
        while cur is not None:
            chain.append(cur.id)
            cur = units.get(cur.parent_id) if cur.parent_id else None
        chains[uid] = chain
    return units, chains


def employees_in(db: Session, condition) -> list[EmployeeProfile]:
    return list(db.scalars(select(EmployeeProfile).where(condition).order_by(EmployeeProfile.pseudonym)))


def registry(db: Session) -> ModelRegistry | None:
    return db.scalar(select(ModelRegistry).where(ModelRegistry.name == MODEL_NAME))
