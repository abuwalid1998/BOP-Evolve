"""Macroevolution-inspired learning profile (G0 → Gx).

"Generation" is a versioned learning-history metaphor, not a measure of a
person's worth. Generations only advance when evidence gates are met — never
because time passed or a course was opened. History is append-only: each
evaluation that changes the profile creates a new, *proposed* version that a
manager or HR must approve before it becomes the current version (Gx).

The indicator weights below are ILLUSTRATIVE MOCK SETTINGS ONLY. They are not
approved employment criteria and must be validated by HR, Risk, Compliance and
model-governance owners before any real use.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    CoachingSession,
    EmployeeResponse,
    Finding,
    ImprovementAction,
    LearningGeneration,
    ReviewDecision,
    ServiceCase,
    TrainingRecord,
)

METHOD_VERSION = "demo-1.0"
WEIGHTS = {"understanding": 0.25, "action_completion": 0.25, "follow_up": 0.30, "recurrence_trend": 0.20}
WINDOW_DAYS = 365
FOLLOW_UP_DAYS = 90
TREND_DAYS = 90
MIN_FOLLOW_UP_CASES = 5
UNDERSTANDING_THRESHOLD = 0.70
FOLLOW_UP_THRESHOLD = 0.85
MIN_TREND_CASES = 5

_DECISION_STATUS = {"confirm": "CONFIRMED", "amend": "AMENDED", "dispute_upheld": "DISMISSED", "dismiss": "DISMISSED"}
_COUNTED = {"CONFIRMED", "AMENDED"}


@dataclass
class EmployeeEvidence:
    cases: list[ServiceCase]
    findings: list[Finding]
    decisions: list[ReviewDecision]
    responses: list[EmployeeResponse]
    actions: list[ImprovementAction]
    training: list[TrainingRecord]
    coaching: list[CoachingSession]


@dataclass
class Evaluation:
    generation_code: str
    no_open_cycle: bool
    score: float | None
    coverage: float
    evidence_count: int
    indicators: dict = field(default_factory=dict)
    gates: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def snapshot(self, as_of: datetime) -> dict:
        return {
            "as_of": as_of.isoformat(),
            "method_version": METHOD_VERSION,
            "weights": WEIGHTS,
            "weights_note": "Illustrative mock settings only - not approved employment criteria.",
            "window_days": WINDOW_DAYS,
            "indicators": self.indicators,
            "gates": self.gates,
            "gaps": self.gaps,
            "warnings": self.warnings,
            "no_open_cycle": self.no_open_cycle,
        }


def load_evidence(db: Session, employee_id: str) -> EmployeeEvidence:
    cases = list(db.scalars(select(ServiceCase).where(ServiceCase.employee_id == employee_id)))
    case_ids = [c.id for c in cases]
    findings = list(db.scalars(select(Finding).where(Finding.case_id.in_(case_ids)))) if case_ids else []
    finding_ids = [f.id for f in findings]

    def by_finding(model):
        if not finding_ids:
            return []
        return list(db.scalars(select(model).where(model.finding_id.in_(finding_ids))))

    return EmployeeEvidence(
        cases=cases,
        findings=findings,
        decisions=by_finding(ReviewDecision),
        responses=by_finding(EmployeeResponse),
        actions=by_finding(ImprovementAction),
        training=list(db.scalars(select(TrainingRecord).where(TrainingRecord.employee_id == employee_id))),
        coaching=list(db.scalars(select(CoachingSession).where(CoachingSession.employee_id == employee_id))),
    )


def _status_at(finding: Finding, decisions: list[ReviewDecision], as_of: datetime) -> str | None:
    """Finding status as it stood at ``as_of`` according to the immutable decision log."""
    if finding.created_at > as_of:
        return None
    relevant = [d for d in decisions if d.finding_id == finding.id and d.decided_at <= as_of]
    if not relevant:
        return "POTENTIAL"
    return _DECISION_STATUS[max(relevant, key=lambda d: d.decided_at).decision]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def evaluate(ev: EmployeeEvidence, as_of: datetime | None = None) -> Evaluation:
    as_of = as_of or utcnow()
    window_start = as_of - timedelta(days=WINDOW_DAYS)
    case_by_id = {c.id: c for c in ev.cases}
    visible_cases = [c for c in ev.cases if c.occurred_at <= as_of]

    status = {f.id: _status_at(f, ev.decisions, as_of) for f in ev.findings}
    counted = [f for f in ev.findings if status[f.id] in _COUNTED]
    cycle = [f for f in counted if case_by_id[f.case_id].occurred_at >= window_start]
    cycle_ids = {f.id for f in cycle}
    flagged_case_ids = {f.case_id for f in ev.findings if status[f.id] not in (None, "DISMISSED")}

    responses = [r for r in ev.responses if r.submitted_at <= as_of]
    actions = [a for a in ev.actions if a.created_at <= as_of and a.finding_id in cycle_ids and a.status != "cancelled"]
    training = [t for t in ev.training if t.completed_at and t.completed_at <= as_of and t.completed_at >= window_start]
    coaching = [c for c in ev.coaching if c.session_at <= as_of]

    indicators: dict[str, dict] = {}
    warnings: list[str] = []

    # Demonstrated understanding: after-feedback confirmation, knowledge checks, reviewer-observed demonstration.
    u_values: list[float] = []
    for f in cycle:
        after = [r for r in responses if r.finding_id == f.id and r.stage == "after_feedback"]
        if after:
            u_values.append(1.0 if max(after, key=lambda r: r.submitted_at).understood_after_feedback else 0.0)
    u_values += [t.score / 100 for t in training if t.score is not None]
    u_values += [1.0 for c in coaching if c.outcome_code == "demonstrated" and c.session_at >= window_start]
    indicators["understanding"] = {"value": sum(u_values) / len(u_values) if u_values else None, "n": len(u_values)}

    # Completion of agreed corrective actions that are due (or already completed).
    due = [a for a in actions if a.due_at <= as_of or (a.completed_at and a.completed_at <= as_of)]
    done = [a for a in due if a.completed_at and a.completed_at <= as_of]
    indicators["action_completion"] = {"value": len(done) / len(due) if due else None, "n": len(due)}

    # Performance on comparable follow-up cases (same case type, after the finding, within the window).
    comparable = 0
    handled_correctly = 0
    for f in cycle:
        origin = case_by_id[f.case_id]
        horizon = min(origin.occurred_at + timedelta(days=FOLLOW_UP_DAYS), as_of)
        for c in visible_cases:
            if c.case_type == origin.case_type and origin.occurred_at < c.occurred_at <= horizon:
                comparable += 1
                handled_correctly += 0 if c.id in flagged_case_ids else 1
    indicators["follow_up"] = {"value": handled_correctly / comparable if comparable else None, "n": comparable}

    # Recurrence trend, adjusted for exposure (findings per case, recent vs prior period).
    recent_start = as_of - timedelta(days=TREND_DAYS)
    prior_start = recent_start - timedelta(days=TREND_DAYS)
    recent_cases = [c for c in visible_cases if recent_start < c.occurred_at <= as_of]
    prior_cases = [c for c in visible_cases if prior_start < c.occurred_at <= recent_start]
    trend_value = None
    if len(recent_cases) >= MIN_TREND_CASES and len(prior_cases) >= MIN_TREND_CASES:
        recent_rate = sum(c.id in flagged_case_ids for c in recent_cases) / len(recent_cases)
        prior_rate = sum(c.id in flagged_case_ids for c in prior_cases) / len(prior_cases)
        top = max(recent_rate, prior_rate)
        trend_value = 1.0 if top == 0 else _clamp(0.5 + 0.5 * (prior_rate - recent_rate) / top)
    indicators["recurrence_trend"] = {
        "value": trend_value,
        "n": len(recent_cases) + len(prior_cases),
    }

    available = {k: v["value"] for k, v in indicators.items() if v["value"] is not None}
    coverage = sum(WEIGHTS[k] for k in available)
    score = sum(WEIGHTS[k] * v for k, v in available.items()) / coverage if coverage else None
    for key, item in indicators.items():
        item["weight"] = WEIGHTS[key]
        if item["value"] is None:
            warnings.append(f"missing_component:{key}")
    if comparable and comparable < MIN_FOLLOW_UP_CASES:
        warnings.append("low_follow_up_sample")
    warnings.append("synthetic_demo_data")

    # Sequential evidence gates. A generation can never skip a gate.
    def first_response(f: Finding) -> bool:
        return any(r.finding_id == f.id and r.stage == "before_feedback" for r in responses)

    def understood(f: Finding) -> bool:
        after = [r for r in responses if r.finding_id == f.id and r.stage == "after_feedback"]
        return bool(after) and bool(max(after, key=lambda r: r.submitted_at).understood_after_feedback)

    latest_review = max((f.reviewed_at for f in cycle if f.reviewed_at and f.reviewed_at <= as_of), default=None)
    practice_after = [
        c
        for c in coaching
        if c.outcome_code in ("practiced", "demonstrated") and (latest_review is None or c.session_at >= latest_review)
    ]
    findings_with_actions = {a.finding_id for a in actions}

    gate_checks = [
        ("G1", "awaiting_employee_response", bool(cycle) and all(first_response(f) for f in cycle)),
        (
            "G2",
            "understanding_not_confirmed",
            all(understood(f) for f in cycle)
            and (indicators["understanding"]["value"] or 0) >= UNDERSTANDING_THRESHOLD,
        ),
        (
            "G3",
            "actions_outstanding",
            bool(actions)
            and cycle_ids <= findings_with_actions
            and all(a.completed_at and a.completed_at <= as_of for a in actions),
        ),
        ("G4", "no_practice_session", bool(practice_after)),
        (
            "G5",
            "follow_up_not_validated",
            comparable >= MIN_FOLLOW_UP_CASES and (indicators["follow_up"]["value"] or 0) >= FOLLOW_UP_THRESHOLD,
        ),
    ]
    generation = "G0"
    gates: list[dict] = [{"code": "G0", "passed": True}]
    gaps: list[str] = []
    blocked = False
    for code, gap, passed in gate_checks:
        passed = passed and not blocked
        gates.append({"code": code, "passed": passed})
        if passed:
            generation = code
        elif not blocked:
            gaps.append(gap)
            blocked = True

    if not cycle:
        gaps = ["no_open_learning_cycle"]

    evidence_count = len(cycle) + len(responses) + len(done) + len(training) + len(coaching)
    return Evaluation(
        generation_code=generation,
        no_open_cycle=not cycle,
        score=round(score, 4) if score is not None else None,
        coverage=round(coverage, 4),
        evidence_count=evidence_count,
        indicators=indicators,
        gates=gates,
        gaps=gaps,
        warnings=warnings,
    )


def latest_version(db: Session, employee_id: str, *, approved_only: bool = False) -> LearningGeneration | None:
    stmt = select(LearningGeneration).where(LearningGeneration.employee_id == employee_id)
    if approved_only:
        stmt = stmt.where(LearningGeneration.status == "approved")
    else:
        stmt = stmt.where(LearningGeneration.status != "rejected")
    return db.scalar(stmt.order_by(LearningGeneration.version.desc()).limit(1))


def refresh_generation(
    db: Session,
    employee_id: str,
    *,
    as_of: datetime | None = None,
    approver_id: str | None = None,
    evidence: EmployeeEvidence | None = None,
) -> LearningGeneration | None:
    """Evaluate the profile and append a new version if it materially changed.

    With ``approver_id`` the new version is approved immediately (used by the
    seed script to build historical, already-approved history).
    """
    as_of = as_of or utcnow()
    result = evaluate(evidence or load_evidence(db, employee_id), as_of)
    current = latest_version(db, employee_id)

    if current is not None:
        if result.no_open_cycle:
            return None
        same_code = current.generation_code == result.generation_code
        score_delta = abs((current.score or 0) - (result.score or 0))
        if same_code and score_delta < 0.05:
            return None
        if current.status == "proposed":
            current.status = "rejected"  # superseded before approval; kept for the record

    version = (
        db.scalar(
            select(LearningGeneration.version)
            .where(LearningGeneration.employee_id == employee_id)
            .order_by(LearningGeneration.version.desc())
            .limit(1)
        )
        or 0
    ) + 1
    generation = LearningGeneration(
        employee_id=employee_id,
        version=version,
        generation_code=result.generation_code,
        status="proposed",
        effective_at=as_of,
        score=result.score,
        coverage=result.coverage,
        indicator_snapshot=result.snapshot(as_of),
        evidence_count=result.evidence_count,
        method_version=METHOD_VERSION,
        supersedes_id=current.id if current else None,
        created_at=as_of,
    )
    db.add(generation)
    db.flush()
    if approver_id:
        approve(db, generation, approver_id, at=as_of)
    return generation


def approve(db: Session, generation: LearningGeneration, approver_id: str, *, at: datetime | None = None) -> None:
    at = at or utcnow()
    previous = latest_version(db, generation.employee_id, approved_only=True)
    if previous is not None and previous.id != generation.id and previous.end_at is None:
        previous.end_at = generation.effective_at
    generation.status = "approved"
    generation.approved_by = approver_id
    generation.approved_at = at
