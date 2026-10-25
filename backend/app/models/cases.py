from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, new_id, utcnow

FINDING_STATUSES = ("POTENTIAL", "CONFIRMED", "AMENDED", "DISPUTED", "DISMISSED")
SEVERITIES = ("low", "medium", "high", "critical")
AWARENESS_STATES = ("recognized", "not_recognized", "unsure", "disagree")
CONTRIBUTING_FACTORS = (
    "individual_action",
    "policy_ambiguity",
    "process_design",
    "system_issue",
    "workload",
    "undetermined",
)
REVIEW_DECISIONS = ("confirm", "amend", "dispute_upheld", "dismiss")
ACTION_TYPES = ("coaching", "training", "job_aid", "practice", "policy_clarification", "system_fix")
ACTION_STATUSES = ("planned", "in_progress", "completed", "cancelled")
RULE_STATUSES = ("draft", "pending_approval", "active", "retired")
RULE_KINDS = ("breach", "early_warning")
POLICY_STATUSES = ("draft", "pending_approval", "active", "superseded", "retired")


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in values)


class SourceSystem(Base):
    __tablename__ = "source_systems"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("SRC"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    system_type: Mapped[str] = mapped_column(String(40))
    owner: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_for_use: Mapped[bool] = mapped_column(Boolean, default=False)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("POL"))
    policy_code: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    title_ar: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    summary_ar: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    owner_unit_id: Mapped[str | None] = mapped_column(ForeignKey("org_units.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("policy_code", "version", name="uq_policy_versions_code_version"),
        CheckConstraint(f"status IN ({_in(POLICY_STATUSES)})", name="status"),
    )


class MistakeRule(Base):
    """A versioned control rule: conditions over a case's procedural facts.

    ``breach`` rules raise potential findings for human review; ``early_warning`` rules
    only flag circumstances that historically precede breaches, for monitoring and
    forecasting. A version moves draft -> pending_approval -> active -> retired, and the
    approver must differ from the author and the submitter (four-eyes).
    """

    __tablename__ = "mistake_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("RUL"))
    rule_code: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(40), index=True)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    name: Mapped[str] = mapped_column(String(160), default="", server_default="")
    name_ar: Mapped[str] = mapped_column(String(160), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), default="breach", server_default="breach")
    description: Mapped[str] = mapped_column(Text)
    description_ar: Mapped[str] = mapped_column(Text)
    expected_action: Mapped[str] = mapped_column(Text)
    expected_action_ar: Mapped[str] = mapped_column(Text)
    observed_action: Mapped[str | None] = mapped_column(Text)
    observed_action_ar: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    severity: Mapped[str] = mapped_column(String(16))
    base_confidence: Mapped[float] = mapped_column(Float, default=0.8, server_default="0.8")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    review_note: Mapped[str | None] = mapped_column(Text)

    policy_version: Mapped[PolicyVersion] = relationship()

    __table_args__ = (
        UniqueConstraint("rule_code", "version", name="uq_mistake_rules_code_version"),
        CheckConstraint(f"severity IN ({_in(SEVERITIES)})", name="severity"),
        CheckConstraint(f"status IN ({_in(RULE_STATUSES)})", name="status"),
        CheckConstraint(f"kind IN ({_in(RULE_KINDS)})", name="kind"),
        CheckConstraint("base_confidence >= 0 AND base_confidence <= 1", name="base_confidence"),
    )

    @property
    def active(self) -> bool:
        return self.status == "active"


class ServiceCase(Base):
    """Normalised customer-service case metadata (no customer content)."""

    __tablename__ = "service_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("CS"))
    source_system_id: Mapped[str] = mapped_column(ForeignKey("source_systems.id"))
    source_case_key: Mapped[str] = mapped_column(String(80))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    org_unit_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    case_type: Mapped[str] = mapped_column(String(40), index=True)
    interaction_type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    complexity_band: Mapped[str] = mapped_column(String(16))
    policy_version_id: Mapped[str | None] = mapped_column(ForeignKey("policy_versions.id"))
    data_quality_status: Mapped[str] = mapped_column(String(16), default="valid")
    ingestion_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    # Procedural facts the rules engine evaluates (see pipeline.catalogue.FIELDS). No customer data.
    attributes: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    findings: Mapped[list["Finding"]] = relationship(back_populates="case")

    __table_args__ = (
        UniqueConstraint("source_system_id", "source_case_key", name="uq_service_cases_source_key"),
        CheckConstraint("complexity_band IN ('low','medium','high')", name="complexity_band"),
    )


class EvidenceRef(Base):
    """Controlled pointer to evidence held in the approved source system."""

    __tablename__ = "evidence_refs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("EVD"))
    case_id: Mapped[str] = mapped_column(ForeignKey("service_cases.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40))
    secure_reference: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    access_class: Mapped[str] = mapped_column(String(16), default="internal")
    summary: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (CheckConstraint("access_class IN ('internal','restricted')", name="access_class"),)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("FND"))
    case_id: Mapped[str] = mapped_column(ForeignKey("service_cases.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("mistake_rules.id"))
    status: Mapped[str] = mapped_column(String(16), default="POTENTIAL", index=True)
    severity: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(40))
    observed_action: Mapped[str] = mapped_column(Text)
    observed_action_ar: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    explanation_ar: Mapped[str] = mapped_column(Text)
    detection_method: Mapped[str] = mapped_column(String(16), default="rule")
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_registry.id"))
    confidence: Mapped[float | None] = mapped_column(Float)
    contributing_factor: Mapped[str] = mapped_column(String(24), default="undetermined")
    # The rule conditions that matched, with the facts observed, so reviewers see why it was flagged.
    matched_conditions: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    case: Mapped[ServiceCase] = relationship(back_populates="findings")
    rule: Mapped[MistakeRule] = relationship()

    __table_args__ = (
        CheckConstraint(f"status IN ({_in(FINDING_STATUSES)})", name="status"),
        CheckConstraint(f"severity IN ({_in(SEVERITIES)})", name="severity"),
        CheckConstraint(f"contributing_factor IN ({_in(CONTRIBUTING_FACTORS)})", name="contributing_factor"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"),
    )


class EmployeeResponse(Base):
    """Self-reported awareness. Captured explicitly; never inferred from a model score."""

    __tablename__ = "employee_responses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("RSP"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    awareness_state: Mapped[str | None] = mapped_column(String(16))
    understood_after_feedback: Mapped[bool | None] = mapped_column(Boolean)
    contextual_factors: Mapped[list] = mapped_column(JSON, default=list)
    # Prototype stores short synthetic text; production would store a secure reference.
    response_text: Mapped[str | None] = mapped_column(String(1000))
    requested_review: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("stage IN ('before_feedback','after_feedback')", name="stage"),
        CheckConstraint(
            f"awareness_state IS NULL OR awareness_state IN ({_in(AWARENESS_STATES)})", name="awareness_state"
        ),
    )


class ReviewDecision(Base):
    """Immutable human review outcome. A later decision supersedes, never overwrites."""

    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("REV"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    policy_clear: Mapped[bool | None] = mapped_column(Boolean)
    evidence_supports: Mapped[bool | None] = mapped_column(Boolean)
    system_issue_contributed: Mapped[bool | None] = mapped_column(Boolean)
    contributing_factor: Mapped[str] = mapped_column(String(24), default="undetermined")
    amended_severity: Mapped[str | None] = mapped_column(String(16))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (CheckConstraint(f"decision IN ({_in(REVIEW_DECISIONS)})", name="decision"),)


class ImprovementAction(Base):
    __tablename__ = "improvement_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ACT"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completion_evidence_ref: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint(f"action_type IN ({_in(ACTION_TYPES)})", name="action_type"),
        CheckConstraint(f"status IN ({_in(ACTION_STATUSES)})", name="status"),
    )


class FollowUpEvaluation(Base):
    """Result of checking comparable later cases after a confirmed finding."""

    __tablename__ = "follow_up_evaluations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("FUP"))
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    window_days: Mapped[int] = mapped_column(Integer)
    comparable_cases: Mapped[int] = mapped_column(Integer)
    recurrences: Mapped[int] = mapped_column(Integer)
    recurred: Mapped[bool] = mapped_column(Boolean)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
