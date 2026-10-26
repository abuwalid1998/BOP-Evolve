from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow

ATTENDANCE_STATUSES = ("worked", "approved_leave", "unapproved_absence")
EXCEPTION_STATUSES = ("open", "explained", "excused", "confirmed", "dismissed")
EXCEPTION_REASONS = (
    "transport",
    "family",
    "medical",
    "time_clock_error",
    "approved_by_manager",
    "customer_service_overrun",
    "other",
)
EXCEPTION_ACTIONS = ("none", "reminder", "coaching", "schedule_review", "formal_note")
DRESS_ITEMS = ("formal_attire", "id_badge", "uniform", "grooming")


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in values)


class AttendanceDay(Base):
    """One scheduled working day from the time clock. Times are minutes after local midnight."""

    __tablename__ = "attendance_days"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ATT"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    org_unit_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), default="worked")
    scheduled_start_min: Mapped[int] = mapped_column(Integer)
    scheduled_end_min: Mapped[int] = mapped_column(Integer)
    check_in_min: Mapped[int | None] = mapped_column(Integer)
    check_out_min: Mapped[int | None] = mapped_column(Integer)
    minutes_late: Mapped[int] = mapped_column(Integer, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    break_count: Mapped[int] = mapped_column(Integer, default=0)
    break_overrun_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_minutes: Mapped[int] = mapped_column(Integer, default=0)
    customer_facing: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(24), default="time_clock")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_days_employee_date"),
        CheckConstraint(f"status IN ({_in(ATTENDANCE_STATUSES)})", name="status"),
    )


class ConductObservation(Base):
    """A supervisor's check of a workplace standard (dress code) for one employee."""

    __tablename__ = "conduct_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("CDO"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    org_unit_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    category: Mapped[str] = mapped_column(String(24), default="dress_code")
    item: Mapped[str] = mapped_column(String(24))
    compliant: Mapped[bool] = mapped_column(Boolean)
    customer_facing: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    observed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    # Internal note for the employee's file; never sent to the AI assistant.
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("category IN ('dress_code')", name="category"),
        CheckConstraint(f"item IN ({_in(DRESS_ITEMS)})", name="item"),
    )


class WorkplaceException(Base):
    """A workplace-policy rule matched a record. The employee explains, a supervisor decides.

    open -> explained (employee gave a reason) -> excused | confirmed | dismissed (supervisor).
    A supervisor may also decide straight from open (for example a time-clock fault).
    """

    __tablename__ = "workplace_exceptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("WEX"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee_profiles.id"), index=True)
    org_unit_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(32), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("mistake_rules.id"), index=True)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    severity: Mapped[str] = mapped_column(String(16))
    matched_conditions: Mapped[list | None] = mapped_column(JSON(none_as_null=True))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    reason_code: Mapped[str | None] = mapped_column(String(32))
    reason_text: Mapped[str | None] = mapped_column(String(500))
    responded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_note: Mapped[str | None] = mapped_column(String(500))
    action: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "rule_id", name="uq_workplace_exceptions_source_rule"),
        CheckConstraint("source_type IN ('attendance','conduct')", name="source_type"),
        CheckConstraint(f"status IN ({_in(EXCEPTION_STATUSES)})", name="status"),
        CheckConstraint(f"reason_code IS NULL OR reason_code IN ({_in(EXCEPTION_REASONS)})", name="reason_code"),
        CheckConstraint(f"action IS NULL OR action IN ({_in(EXCEPTION_ACTIONS)})", name="action"),
    )
