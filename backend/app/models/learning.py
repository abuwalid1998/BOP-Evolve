from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow

GENERATION_CODES = ("G0", "G1", "G2", "G3", "G4", "G5")


class TrainingRecord(Base):
    __tablename__ = "training_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("TRN"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    course_code: Mapped[str] = mapped_column(String(40))
    related_finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id"))
    status: Mapped[str] = mapped_column(String(16))
    score: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_system_id: Mapped[str | None] = mapped_column(ForeignKey("source_systems.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('assigned','opened','completed','failed')", name="status"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score"),
    )


class CoachingSession(Base):
    __tablename__ = "coaching_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("COA"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    related_finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id"))
    session_at: Mapped[datetime] = mapped_column(UTCDateTime)
    outcome_code: Mapped[str] = mapped_column(String(24))
    reflection: Mapped[str | None] = mapped_column(String(1000))
    notes_ref: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        CheckConstraint(
            "outcome_code IN ('discussed','practiced','demonstrated','needs_follow_up')", name="outcome_code"
        ),
    )


class LearningGeneration(Base):
    """Immutable, versioned learning profile. Corrections create a new version."""

    __tablename__ = "learning_generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("GEN"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    generation_code: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    score: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float, default=0)
    indicator_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    method_version: Mapped[str] = mapped_column(String(24))
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("learning_generations.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("generation_code IN ('G0','G1','G2','G3','G4','G5')", name="generation_code"),
        CheckConstraint("status IN ('proposed','approved','rejected')", name="status"),
    )
