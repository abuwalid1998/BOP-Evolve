"""Synthetic workplace-policy history: time-clock days, dress-code observations and exceptions.

Used by the seed (new databases) and by ``app.seed.upgrade`` (databases seeded before the
workplace module existed). Everything here is simulated and labelled ``source='simulated'``.
"""

import random
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import new_id, utcnow
from app.models import (
    AttendanceDay,
    EmployeeProfile,
    MistakeRule,
    OrgUnit,
    PolicyVersion,
    User,
    WorkplaceException,
)
from app.pipeline.catalogue import WORKPLACE_POLICIES, WORKPLACE_RULES
from app.services import settings_store, workplace

HISTORY_DAYS = 120
SETTLE_AFTER_DAYS = 10
CALM_REASONS = {"transport", "time_clock_error", "approved_by_manager", "customer_service_overrun", "medical"}


def ensure_reference(
    db: Session, owner_unit_id: str | None, author_id: str | None, approver_id: str | None, effective_from: datetime
) -> list[str]:
    """Create the HR-01..03 policies and their rules when missing. Returns what was added."""
    added = []
    policies = {}
    for code, spec in WORKPLACE_POLICIES.items():
        policy = db.scalar(
            select(PolicyVersion).where(PolicyVersion.policy_code == code).order_by(PolicyVersion.created_at.desc())
        )
        if policy is None:
            policy = PolicyVersion(
                id=new_id("POL"),
                policy_code=code,
                version="1.0",
                title=spec["title"][0],
                title_ar=spec["title"][1],
                summary=spec["summary"][0],
                summary_ar=spec["summary"][1],
                effective_from=effective_from,
                owner_unit_id=owner_unit_id,
                approved_at=effective_from - timedelta(days=7),
                status="active",
                created_by=author_id,
                submitted_by=author_id,
                approved_by=approver_id,
                created_at=effective_from - timedelta(days=14),
                submitted_at=effective_from - timedelta(days=12),
            )
            db.add(policy)
            added.append(f"policy:{code}")
        policies[code] = policy
    db.flush()
    for rule_code, spec in WORKPLACE_RULES.items():
        if db.scalar(select(MistakeRule.id).where(MistakeRule.rule_code == rule_code)) is not None:
            continue
        policy = policies[spec["policy"]]
        db.add(
            MistakeRule(
                id=new_id("RUL"),
                rule_code=rule_code,
                version="1",
                category=spec["category"],
                policy_version_id=policy.id,
                name=spec["name"][0],
                name_ar=spec["name"][1],
                kind="breach",
                description=spec["description"][0],
                description_ar=spec["description"][1],
                expected_action=spec["expected"][0],
                expected_action_ar=spec["expected"][1],
                observed_action=spec["observed"][0],
                observed_action_ar=spec["observed"][1],
                conditions=spec["conditions"],
                severity=spec["severity"],
                base_confidence=0.95,
                status="active",
                created_by=author_id,
                submitted_by=author_id,
                approved_by=approver_id,
                created_at=policy.created_at,
                submitted_at=policy.submitted_at,
                approved_at=policy.approved_at,
            )
        )
        added.append(f"rule:{rule_code}")
    db.flush()
    return added


def _reviewers(db: Session) -> dict[str, str]:
    """Section unit id -> the team lead's user id (``lead.<section code>`` in the demo)."""
    leads = {u.username: u.id for u in db.scalars(select(User).where(User.username.like("lead.%")))}
    return {
        unit.id: leads[f"lead.{unit.code.lower()}"]
        for unit in db.scalars(select(OrgUnit).where(OrgUnit.unit_type == "section"))
        if f"lead.{unit.code.lower()}" in leads
    }


def _settle(
    x: WorkplaceException, rng: random.Random, today: date, reviewer: str | None, responder: str | None
) -> None:
    """Give an exception a plausible workflow state for its age."""
    age = (today - x.occurred_on).days
    roll = rng.random()
    explained = rng.random() < 0.6
    decided = roll < (0.9 if age > SETTLE_AFTER_DAYS else 0.15)
    occurred = datetime.combine(x.occurred_on, time(15, 0), tzinfo=UTC)
    if explained or decided:
        if explained:
            x.reason_code = rng.choices(
                (
                    "transport",
                    "family",
                    "medical",
                    "time_clock_error",
                    "approved_by_manager",
                    "customer_service_overrun",
                    "other",
                ),
                (30, 14, 8, 12, 12, 16, 8),
            )[0]
            x.responded_by = responder
            x.responded_at = occurred + timedelta(hours=rng.uniform(2, 40))
            x.status = "explained"
    if not decided:
        return
    calm = x.reason_code in CALM_REASONS
    x.status = rng.choices(("excused", "confirmed", "dismissed"), (45, 45, 10) if calm else (15, 75, 10))[0]
    if x.reason_code == "time_clock_error" and rng.random() < 0.7:
        x.status = "dismissed"
    x.decided_by = reviewer
    x.decided_at = (x.responded_at or occurred) + timedelta(hours=rng.uniform(4, 72))
    if x.status == "confirmed":
        x.action = rng.choices(
            ("reminder", "coaching", "schedule_review", "formal_note"),
            (50, 30, 12, 8) if x.severity != "high" else (20, 35, 15, 30),
        )[0]


def seed_history(db: Session, today: date | None = None, days: int = HISTORY_DAYS) -> dict:
    """Simulate history for demo employees (not roster imports) that have no time-clock days yet."""
    today = today or utcnow().date()
    allowance = settings_store.get(db, "workplace.break_allowance_minutes")
    have = set(db.scalars(select(AttendanceDay.employee_id).distinct()))
    employees = [
        e
        for e in db.scalars(
            select(EmployeeProfile).where(EmployeeProfile.external_ref.is_(None)).order_by(EmployeeProfile.pseudonym)
        )
        if e.id not in have
    ]
    if not employees:
        return {"employees": 0, "days": 0, "observations": 0, "exceptions": 0}
    reviewers = _reviewers(db)
    att_rules = workplace.active_rules(db, "attendance")
    rng = random.Random("workplace-seed")
    total_days = total_obs = total_exc = 0
    for employee in employees:
        responder = employee.user_id
        reviewer = reviewers.get(employee.org_unit_id)
        rows = []
        day = today - timedelta(days=days)
        while day < today:
            if workplace.is_working_day(day):
                rows.append(workplace.simulate_day(employee, day, today, allowance))
            day += timedelta(days=1)
        db.add_all(rows)
        db.flush()
        raised = workplace.raise_exceptions(db, [workplace.attendance_item(r) for r in rows], att_rules)
        # Supervisors check dress code roughly every two weeks.
        when = datetime.combine(today - timedelta(days=days - rng.randint(0, 6)), time(9, 30), tzinfo=UTC)
        while when.date() < today:
            if workplace.is_working_day(when.date()):
                item, ok = workplace.simulate_observation(employee, when)
                _, more = workplace.record_observation(db, employee, item, ok, None, reviewer, when)
                raised += more
                total_obs += 1
            when += timedelta(days=rng.randint(10, 18), minutes=rng.randint(-60, 240))
        recent_demo = employee.user_id is not None  # leave the demo employee something to respond to
        for x in raised:
            if recent_demo and (today - x.occurred_on).days <= 30:
                continue
            _settle(x, rng, today, reviewer, responder)
        total_days += len(rows)
        total_exc += len(raised)
    db.flush()
    return {"employees": len(employees), "days": total_days, "observations": total_obs, "exceptions": total_exc}


def ensure_for_existing(db: Session) -> list[str]:
    """Upgrade path: policies, rules and simulated history for a database seeded before this module."""
    owner_unit = db.scalar(select(OrgUnit.id).where(OrgUnit.code == "DEP-OPS"))
    author = db.scalar(select(User.id).where(User.username == "hr.chief"))
    approver = db.scalar(select(User.id).where(User.username == "risk.compliance"))
    start = utcnow() - timedelta(days=HISTORY_DAYS + 30)
    added = ensure_reference(db, owner_unit, author, approver, start)
    if db.scalar(select(func.count()).select_from(AttendanceDay)) == 0:
        counts = seed_history(db)
        if counts["days"]:
            added.append(f"attendance:{counts['days']}")
    return added
