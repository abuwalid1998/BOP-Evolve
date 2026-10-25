"""Unit tests for the evidence-gated learning generations (no database needed)."""

from datetime import timedelta

import pytest

from app.config import Settings
from app.db import utcnow
from app.models import (
    CoachingSession,
    EmployeeResponse,
    Finding,
    ImprovementAction,
    ReviewDecision,
    ServiceCase,
    TrainingRecord,
)
from app.services.audit import _redact
from app.services.learning import EmployeeEvidence, evaluate

NOW = utcnow()


def _case(i: int, days_ago: float, case_type: str = "transfers") -> ServiceCase:
    return ServiceCase(
        id=f"CS-{i}",
        employee_id="E",
        org_unit_id="U",
        case_type=case_type,
        occurred_at=NOW - timedelta(days=days_ago),
        source_system_id="S",
        source_case_key=str(i),
        interaction_type="phone",
        complexity_band="low",
    )


def _evidence(**overrides) -> EmployeeEvidence:
    cases = [_case(0, 60)] + [_case(i, 60 - i * 3) for i in range(1, 12)]
    finding = Finding(
        id="F1",
        case_id="CS-0",
        rule_id="R",
        status="CONFIRMED",
        severity="high",
        created_at=NOW - timedelta(days=59),
        reviewed_at=NOW - timedelta(days=55),
    )
    base = dict(
        cases=cases,
        findings=[finding],
        decisions=[ReviewDecision(finding_id="F1", decision="confirm", decided_at=NOW - timedelta(days=55))],
        responses=[],
        actions=[],
        training=[],
        coaching=[],
    )
    base.update(overrides)
    return EmployeeEvidence(**base)


def test_no_findings_stays_at_baseline():
    result = evaluate(
        EmployeeEvidence(
            cases=[_case(0, 10)], findings=[], decisions=[], responses=[], actions=[], training=[], coaching=[]
        )
    )
    assert result.generation_code == "G0"
    assert result.no_open_cycle


def test_generation_requires_employee_response_first():
    result = evaluate(_evidence())
    assert result.generation_code == "G0"
    assert result.gaps == ["awaiting_employee_response"]


def test_gates_cannot_be_skipped():
    # Coaching practice and completed actions exist, but understanding was never confirmed.
    evidence = _evidence(
        responses=[
            EmployeeResponse(
                finding_id="F1",
                stage="before_feedback",
                awareness_state="unsure",
                submitted_at=NOW - timedelta(days=56),
            )
        ],
        actions=[
            ImprovementAction(
                finding_id="F1",
                action_type="coaching",
                status="completed",
                created_at=NOW - timedelta(days=55),
                due_at=NOW - timedelta(days=40),
                completed_at=NOW - timedelta(days=45),
            )
        ],
        coaching=[CoachingSession(session_at=NOW - timedelta(days=45), outcome_code="demonstrated")],
    )
    result = evaluate(evidence)
    assert result.generation_code == "G1"
    assert result.gaps == ["understanding_not_confirmed"]
    assert [g["passed"] for g in result.gates] == [True, True, False, False, False, False]


def test_full_evidence_reaches_validation():
    evidence = _evidence(
        responses=[
            EmployeeResponse(
                finding_id="F1",
                stage="before_feedback",
                awareness_state="not_recognized",
                submitted_at=NOW - timedelta(days=56),
            ),
            EmployeeResponse(
                finding_id="F1",
                stage="after_feedback",
                understood_after_feedback=True,
                submitted_at=NOW - timedelta(days=54),
            ),
        ],
        actions=[
            ImprovementAction(
                finding_id="F1",
                action_type="training",
                status="completed",
                created_at=NOW - timedelta(days=55),
                due_at=NOW - timedelta(days=40),
                completed_at=NOW - timedelta(days=50),
            )
        ],
        training=[TrainingRecord(score=92, status="completed", completed_at=NOW - timedelta(days=50))],
        coaching=[CoachingSession(session_at=NOW - timedelta(days=48), outcome_code="practiced")],
    )
    result = evaluate(evidence)
    assert result.generation_code == "G5"
    assert result.indicators["follow_up"]["n"] >= 5
    assert 0 < result.coverage <= 1
    assert "synthetic_demo_data" in result.warnings


def test_evaluation_ignores_future_evidence():
    evidence = _evidence(
        responses=[
            EmployeeResponse(
                finding_id="F1",
                stage="before_feedback",
                awareness_state="recognized",
                submitted_at=NOW - timedelta(days=1),
            )
        ],
    )
    assert evaluate(evidence, as_of=NOW - timedelta(days=10)).generation_code == "G0"
    assert evaluate(evidence, as_of=NOW).generation_code == "G1"


def test_production_refuses_mock_auth():
    with pytest.raises(RuntimeError):
        Settings(app_env="production", auth_mode="mock", demo_mode=False).assert_safe_for_environment()


def test_audit_metadata_redaction():
    clean = _redact({"password": "x", "nested": {"token": "y"}, "keep": 1})
    assert clean == {"password": "[redacted]", "nested": {"token": "[redacted]"}, "keep": 1}


def test_recent_finding_does_not_reset_profile():
    responses = [
        EmployeeResponse(
            finding_id="F1",
            stage="before_feedback",
            awareness_state="recognized",
            submitted_at=NOW - timedelta(days=56),
        ),
    ]
    recent_case = _case(99, 5)
    recent = Finding(
        id="F2",
        case_id="CS-99",
        rule_id="R",
        status="CONFIRMED",
        severity="low",
        created_at=NOW - timedelta(days=4),
        reviewed_at=NOW - timedelta(days=2),
    )
    base = _evidence(responses=responses)
    evidence = _evidence(
        cases=[*base.cases, recent_case],
        findings=[*base.findings, recent],
        decisions=[
            *base.decisions,
            ReviewDecision(finding_id="F2", decision="confirm", decided_at=NOW - timedelta(days=2)),
        ],
        responses=responses,
    )
    result = evaluate(evidence)
    assert result.generation_code == "G1"
    assert "recent_finding_in_progress" in result.gaps
