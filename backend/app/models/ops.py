from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow

PIPELINE_STATES = ("HEALTHY", "RUNNING", "DEGRADED", "FAILED", "PAUSED", "STALE")
MODEL_STATES = (
    "DEVELOPMENT",
    "VALIDATION",
    "APPROVED",
    "DEPLOYED",
    "MONITORING",
    "DEGRADED",
    "SUSPENDED",
    "RETIRED",
)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("PIP"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    source_system_id: Mapped[str] = mapped_column(ForeignKey("source_systems.id"))
    state: Mapped[str] = mapped_column(String(16), default="HEALTHY")
    state_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    schedule_seconds: Mapped[int] = mapped_column(Integer, default=60)
    freshness_sla_minutes: Mapped[int] = mapped_column(Integer, default=30)
    queue_lag_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_request_id: Mapped[str | None] = mapped_column(String(40))
    owner: Mapped[str] = mapped_column(String(120))
    runbook_url: Mapped[str] = mapped_column(String(255))
    # Behaviour of the simulated connector: stable | flaky | failing | slow
    demo_profile: Mapped[str] = mapped_column(String(16), default="stable")

    __table_args__ = (
        CheckConstraint("state IN ('HEALTHY','RUNNING','DEGRADED','FAILED','PAUSED','STALE')", name="state"),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("RUN"))
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id"), index=True)
    source_system_id: Mapped[str] = mapped_column(ForeignKey("source_systems.id"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16))
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    records_duplicated: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    request_id: Mapped[str] = mapped_column(String(40))
    error_summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint("status IN ('running','succeeded','partial','failed')", name="status"),)


class QuarantinedRecord(Base):
    """Malformed or unexpected records are quarantined, never silently dropped."""

    __tablename__ = "quarantined_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("QRN"))
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True)
    source_record_key: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(200))
    payload_redacted: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("MDL"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    state_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    owner: Mapped[str] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_validation_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    latency_ms_p50: Mapped[float | None] = mapped_column(Float)
    missing_input_rate: Mapped[float | None] = mapped_column(Float)
    drift_score: Mapped[float | None] = mapped_column(Float)
    override_rate: Mapped[float | None] = mapped_column(Float)
    limitations: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('DEVELOPMENT','VALIDATION','APPROVED','DEPLOYED','MONITORING','DEGRADED','SUSPENDED','RETIRED')",
            name="status",
        ),
    )


class ModelRun(Base):
    """Versioned inference record. Never overwritten."""

    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("MRN"))
    model_id: Mapped[str] = mapped_column(ForeignKey("model_registry.id"), index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("service_cases.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    output_summary: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("SIM"))
    scenario_code: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str | None] = mapped_column(ForeignKey("model_registry.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    illustrative: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_beat_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditEvent(Base):
    """Access and change audit. Never store secrets or unredacted sensitive content here."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("AUD"))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    request_id: Mapped[str | None] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    metadata_redacted: Mapped[dict] = mapped_column(JSON, default=dict)
