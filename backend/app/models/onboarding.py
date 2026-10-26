from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow

IMPORT_STATUSES = ("validated", "committed", "failed")
WAVE_STATUSES = ("planned", "launched", "completed")


class OnboardingImport(Base):
    """A staff roster file from the HR system, validated before anything is written.

    ``rows`` holds the normalised valid rows so that committing writes exactly what was previewed.
    """

    __tablename__ = "onboarding_imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("IMP"))
    file_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="validated")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    summary: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    rows: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (CheckConstraint("status IN ('validated','committed','failed')", name="status"),)


class OnboardingWave(Base):
    """A group of staff invited together (for example head office first, then each region)."""

    __tablename__ = "onboarding_waves"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("WAV"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    criteria: Mapped[dict] = mapped_column(JSON)
    starts_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    employee_count: Mapped[int] = mapped_column(Integer, default=0)
    reminder_message: Mapped[str | None] = mapped_column(Text)
    reminder_message_ar: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    launched_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    launched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (CheckConstraint("status IN ('planned','launched','completed')", name="status"),)


class OnboardingInvite(Base):
    """A one-time activation code. Only its SHA-256 hash is stored; the code is shown once at launch."""

    __tablename__ = "onboarding_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("INV"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    wave_id: Mapped[str | None] = mapped_column(ForeignKey("onboarding_waves.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OnboardingProgress(Base):
    """Where one person is in the welcome journey."""

    __tablename__ = "onboarding_progress"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("OBP"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    wave_id: Mapped[str | None] = mapped_column(ForeignKey("onboarding_waves.id"), index=True)
    invited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    language_set_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tour_done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    policies_ack_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    quiz_passed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    quiz_score: Mapped[int | None] = mapped_column(Integer)
    quiz_attempts: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PolicyAcknowledgement(Base):
    """A person confirmed they read a specific policy version."""

    __tablename__ = "policy_acknowledgements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ACK"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "policy_version_id", name="uq_policy_ack_user_version"),)
