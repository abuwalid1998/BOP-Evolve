"""Workplace policies: attendance, breaks and dress code.

Daily time-clock records (``attendance_days``) and supervisor observations
(``conduct_observations``) are evaluated by the same rules engine as customer-service
cases, using the ``attendance`` and ``dress_code`` rule categories. A match raises a
``workplace_exception``: the employee explains, a supervisor decides (excused, confirmed
or dismissed) and may set a light-touch action.

KPIs are SQL aggregates so that they stay fast for thousands of employees. In this
prototype the time clock is simulated (``simulate_day``); a real deployment would feed
``attendance_days`` from the bank's time-and-attendance system instead.
"""

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, case, false, func, or_, select, true
from sqlalchemy.orm import Session

from app.models import AttendanceDay, ConductObservation, EmployeeProfile, MistakeRule, OrgUnit, WorkplaceException
from app.models.workplace import DRESS_ITEMS
from app.services import rules_engine, settings_store
from app.services.rbac import Scope

WEEKDAY_CODES = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
WORKING_DAYS_PER_MONTH = 22
# rules_engine backtest vocabulary for exception outcomes.
STATUS_FOR_BACKTEST = {
    "confirmed": "CONFIRMED",
    "excused": "DISMISSED",
    "dismissed": "DISMISSED",
    "open": "POTENTIAL",
    "explained": "POTENTIAL",
}


def is_working_day(day: date) -> bool:
    return day.weekday() != 4  # Friday is the weekly day off in the demo calendar


def clock(minutes: int | None) -> str | None:
    return None if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"


# ----------------------------------------------------------------------- facts
def attendance_facts(row) -> dict:
    """Rule facts for one attendance day (an ``AttendanceDay`` or a row with the same columns)."""
    worked = row.status == "worked"
    facts = {
        "unapproved_absence": row.status == "unapproved_absence",
        "customer_facing": bool(row.customer_facing),
        "weekday": WEEKDAY_CODES[row.work_date.weekday()],
    }
    if not worked:
        return facts
    facts.update(
        {
            "missing_check_in": row.check_in_min is None,
            "missing_check_out": row.check_out_min is None,
            "minutes_late": row.minutes_late if row.check_in_min is not None else None,
            "early_leave_minutes": row.early_leave_minutes if row.check_out_min is not None else None,
            "break_minutes": row.break_minutes,
            "break_overrun_minutes": row.break_overrun_minutes,
            "break_count": row.break_count,
        }
    )
    return facts


def conduct_facts(obs, prior_issues: int) -> dict:
    return {
        "dress_item": obs.item,
        "dress_compliant": bool(obs.compliant),
        "customer_facing": bool(obs.customer_facing),
        "prior_dress_issues_90d": prior_issues,
    }


def _prior_issues(db: Session, employee_id: str, before: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ConductObservation)
            .where(
                ConductObservation.employee_id == employee_id,
                ConductObservation.compliant.is_(False),
                ConductObservation.observed_at < before,
                ConductObservation.observed_at >= before - timedelta(days=90),
            )
        )
        or 0
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


_ATT_COLUMNS = (
    AttendanceDay.id,
    AttendanceDay.work_date,
    AttendanceDay.status,
    AttendanceDay.check_in_min,
    AttendanceDay.check_out_min,
    AttendanceDay.minutes_late,
    AttendanceDay.early_leave_minutes,
    AttendanceDay.break_minutes,
    AttendanceDay.break_overrun_minutes,
    AttendanceDay.break_count,
    AttendanceDay.customer_facing,
    AttendanceDay.org_unit_id,
    AttendanceDay.employee_id,
)


def history(db: Session, case_type: str, since: datetime) -> tuple[list, dict[str, set[str]]]:
    """Rows and outcome statuses in the shape ``rules_engine.backtest`` expects."""
    rows = []
    if case_type == "attendance":
        for r in db.execute(
            select(*_ATT_COLUMNS).where(AttendanceDay.work_date >= since.date()).order_by(AttendanceDay.work_date)
        ):
            rows.append((r.id, _midnight(r.work_date), attendance_facts(r), r.org_unit_id, r.employee_id))
        source_type = "attendance"
    else:
        observations = db.execute(
            select(ConductObservation)
            .where(ConductObservation.observed_at >= since - timedelta(days=90))
            .order_by(ConductObservation.observed_at)
        ).scalars()
        recent_issues: dict[str, list[datetime]] = defaultdict(list)
        for obs in observations:
            issues = [t for t in recent_issues[obs.employee_id] if t >= obs.observed_at - timedelta(days=90)]
            recent_issues[obs.employee_id] = issues
            if obs.observed_at >= since:
                rows.append(
                    (obs.id, obs.observed_at, conduct_facts(obs, len(issues)), obs.org_unit_id, obs.employee_id)
                )
            if not obs.compliant:
                issues.append(obs.observed_at)
        source_type = "conduct"
    statuses: dict[str, set[str]] = {}
    for source_id, status in db.execute(
        select(WorkplaceException.source_id, WorkplaceException.status).where(
            WorkplaceException.source_type == source_type, WorkplaceException.occurred_on >= since.date()
        )
    ):
        statuses.setdefault(source_id, set()).add(STATUS_FOR_BACKTEST[status])
    return rows, statuses


# ------------------------------------------------------------------ evaluation
def active_rules(db: Session, category: str) -> list[MistakeRule]:
    return list(
        db.scalars(
            select(MistakeRule).where(
                MistakeRule.category == category, MistakeRule.status == "active", MistakeRule.kind == "breach"
            )
        )
    )


def raise_exceptions(db: Session, items: list[dict], rules: list[MistakeRule]) -> list[WorkplaceException]:
    """Evaluate ``rules`` on each item and add an exception per match.

    Each item: ``source_type, source_id, employee_id, org_unit_id, occurred_on, facts``.
    Re-running on the same record does not duplicate exceptions.
    """
    if not items or not rules:
        return []
    existing = set()
    ids = [i["source_id"] for i in items]
    for start in range(0, len(ids), 900):
        existing.update(
            db.execute(
                select(WorkplaceException.source_id, WorkplaceException.rule_id).where(
                    WorkplaceException.source_id.in_(ids[start : start + 900])
                )
            ).all()
        )
    created = []
    for item in items:
        for rule in rules:
            if (item["source_id"], rule.id) in existing:
                continue
            hit, _ = rules_engine.evaluate(rule.conditions, item["facts"])
            if not hit:
                continue
            exc = WorkplaceException(
                employee_id=item["employee_id"],
                org_unit_id=item["org_unit_id"],
                source_type=item["source_type"],
                source_id=item["source_id"],
                rule_id=rule.id,
                occurred_on=item["occurred_on"],
                severity=rule.severity,
                matched_conditions=rules_engine.matched_detail(rule.conditions, item["facts"]),
                status="open",
            )
            db.add(exc)
            created.append(exc)
    return created


def attendance_item(day: AttendanceDay) -> dict:
    return {
        "source_type": "attendance",
        "source_id": day.id,
        "employee_id": day.employee_id,
        "org_unit_id": day.org_unit_id,
        "occurred_on": day.work_date,
        "facts": attendance_facts(day),
    }


def record_observation(
    db: Session,
    employee: EmployeeProfile,
    item: str,
    compliant: bool,
    note: str | None,
    observer_id: str | None,
    observed_at: datetime,
) -> tuple[ConductObservation, list[WorkplaceException]]:
    if item not in DRESS_ITEMS:
        raise ValueError("item")
    prior = _prior_issues(db, employee.id, observed_at)
    obs = ConductObservation(
        employee_id=employee.id,
        org_unit_id=employee.org_unit_id,
        item=item,
        compliant=compliant,
        customer_facing=employee.customer_facing,
        observed_at=observed_at,
        observed_by=observer_id,
        note=note,
    )
    db.add(obs)
    db.flush()
    raised = raise_exceptions(
        db,
        [
            {
                "source_type": "conduct",
                "source_id": obs.id,
                "employee_id": employee.id,
                "org_unit_id": employee.org_unit_id,
                "occurred_on": observed_at.date(),
                "facts": conduct_facts(obs, prior),
            }
        ],
        active_rules(db, "dress_code"),
    )
    return obs, raised


# ------------------------------------------------------------------ simulation
@dataclass(frozen=True)
class Habits:
    late: float
    early: float
    missing_punch: float
    absence: float
    leave: float
    long_break: float
    dress_issue: float
    trend: float  # > 0: was worse earlier in the window and is improving


def habits(key: str) -> Habits:
    """Stable per-employee tendencies for the simulated time clock (keyed by pseudonym)."""
    rng = random.Random(f"wp:{key}")
    tier = rng.random()
    scale = 0.4 if tier < 0.55 else 1.0 if tier < 0.9 else 2.2  # most staff are punctual; a few are not
    return Habits(
        late=min(0.6, rng.uniform(0.02, 0.12) * scale),
        early=min(0.3, rng.uniform(0.005, 0.05) * scale),
        missing_punch=rng.uniform(0.004, 0.025),
        absence=min(0.05, rng.uniform(0.001, 0.008) * scale),
        leave=rng.uniform(0.02, 0.05),
        long_break=min(0.4, rng.uniform(0.02, 0.10) * scale),
        dress_issue=min(0.4, rng.uniform(0.02, 0.10) * scale),
        trend=rng.uniform(-0.3, 0.9),
    )


def simulate_day(employee: EmployeeProfile, day: date, today: date, allowance: int) -> AttendanceDay:
    """One simulated time-clock day. Deterministic for (employee, day)."""
    h = habits(employee.pseudonym)
    rng = random.Random(f"att:{employee.pseudonym}:{day.isoformat()}")
    age = min(120, max(0, (today - day).days))
    factor = max(0.25, 1 + h.trend * (age / 120 - 0.3))
    start, end = employee.work_start_min, employee.work_end_min
    row = AttendanceDay(
        employee_id=employee.id,
        org_unit_id=employee.org_unit_id,
        work_date=day,
        scheduled_start_min=start,
        scheduled_end_min=end,
        scheduled_minutes=end - start,
        customer_facing=employee.customer_facing,
        source="simulated",
    )
    roll = rng.random()
    if roll < h.leave:
        row.status = "approved_leave"
        return row
    if roll < h.leave + h.absence * factor:
        row.status = "unapproved_absence"
        return row
    row.status = "worked"
    if rng.random() < h.late * factor:
        late = 11 + int(rng.expovariate(1 / 14))
    else:
        late = rng.choice([0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 8])
    arrival = start + late - (rng.randint(0, 20) if late == 0 else 0)
    if rng.random() < h.early * factor:
        early = 11 + int(rng.expovariate(1 / 20))
    else:
        early = 0
    departure = end - early + (rng.randint(0, 25) if early == 0 else 0)
    breaks = rng.choice([1, 1, 2, 2, 2, 3])
    total = max(10, int(rng.gauss(allowance * 0.75, 8)))
    if rng.random() < h.long_break * factor:
        total = allowance + 11 + int(rng.expovariate(1 / 15))
    total = min(total, allowance * 3)
    row.check_in_min, row.check_out_min = arrival, departure
    if rng.random() < h.missing_punch:
        if rng.random() < 0.7:
            row.check_out_min = None
        else:
            row.check_in_min = None
    row.minutes_late = max(0, arrival - start) if row.check_in_min is not None else 0
    row.early_leave_minutes = max(0, end - departure) if row.check_out_min is not None else 0
    row.break_count, row.break_minutes = breaks, total
    row.break_overrun_minutes = max(0, total - allowance)
    if row.check_in_min is not None and row.check_out_min is not None:
        row.worked_minutes = max(0, row.check_out_min - row.check_in_min - total)
    else:
        row.worked_minutes = 0
    return row


def simulate_observation(employee: EmployeeProfile, when: datetime) -> tuple[str, bool]:
    h = habits(employee.pseudonym)
    rng = random.Random(f"obs:{employee.pseudonym}:{when.date().isoformat()}")
    items = ["formal_attire", "id_badge", "grooming"] + (["uniform"] if employee.customer_facing else [])
    return rng.choice(items), rng.random() >= h.dress_issue


def backfill(db: Session, employees: list[EmployeeProfile], days: int, today: date, *, limit: int) -> int:
    """Simulate missing time-clock days (up to ``limit`` rows) for ``employees`` and evaluate them."""
    if not employees:
        return 0
    allowance = settings_store.get(db, "workplace.break_allowance_minutes")
    first = today - timedelta(days=days)
    ids = [e.id for e in employees]
    have: dict[str, set[date]] = defaultdict(set)
    for start in range(0, len(ids), 900):
        for emp_id, work_date in db.execute(
            select(AttendanceDay.employee_id, AttendanceDay.work_date).where(
                AttendanceDay.employee_id.in_(ids[start : start + 900]), AttendanceDay.work_date >= first
            )
        ):
            have[emp_id].add(work_date)
    new_rows: list[AttendanceDay] = []
    for employee in employees:
        if employee.start_date and employee.start_date > today:
            continue
        day = max(first, employee.start_date or first)
        while day < today and len(new_rows) < limit:
            if is_working_day(day) and day not in have[employee.id]:
                new_rows.append(simulate_day(employee, day, today, allowance))
            day += timedelta(days=1)
        if len(new_rows) >= limit:
            break
    if not new_rows:
        return 0
    db.add_all(new_rows)
    db.flush()
    raise_exceptions(db, [attendance_item(r) for r in new_rows], active_rules(db, "attendance"))
    return len(new_rows)


# ------------------------------------------------------------------------ KPIs
def scope_condition(scope: Scope, unit_col, employee_col):
    if scope.all:
        return true()
    conds = []
    if scope.org_unit_ids:
        conds.append(unit_col.in_(scope.org_unit_ids))
    if scope.employee_ids:
        conds.append(employee_col.in_(scope.employee_ids))
    return or_(*conds) if conds else false()


def _attendance_sums(grace: int):
    worked = AttendanceDay.status == "worked"
    has_in = and_(worked, AttendanceDay.check_in_min.is_not(None))
    one = lambda cond: func.coalesce(func.sum(case((cond, 1), else_=0)), 0)  # noqa: E731
    total = lambda col: func.coalesce(func.sum(case((worked, col), else_=0)), 0)  # noqa: E731
    return (
        func.count(AttendanceDay.id).label("scheduled"),
        one(worked).label("worked"),
        one(AttendanceDay.status == "approved_leave").label("leave"),
        one(AttendanceDay.status == "unapproved_absence").label("absent"),
        one(has_in).label("with_check_in"),
        one(and_(has_in, AttendanceDay.minutes_late <= grace)).label("on_time"),
        one(and_(has_in, AttendanceDay.minutes_late > grace)).label("late_days"),
        one(and_(worked, AttendanceDay.check_out_min.is_not(None), AttendanceDay.early_leave_minutes > grace)).label(
            "early_days"
        ),
        one(and_(worked, or_(AttendanceDay.check_in_min.is_(None), AttendanceDay.check_out_min.is_(None)))).label(
            "missing_punch"
        ),
        one(and_(worked, AttendanceDay.break_overrun_minutes > 0)).label("break_over_days"),
        total(AttendanceDay.minutes_late).label("late_minutes"),
        func.coalesce(
            func.sum(case((and_(has_in, AttendanceDay.minutes_late > grace), AttendanceDay.minutes_late), else_=0)), 0
        ).label("late_minutes_beyond_grace"),
        total(AttendanceDay.early_leave_minutes).label("early_minutes"),
        total(AttendanceDay.break_overrun_minutes).label("overrun_minutes"),
        total(AttendanceDay.break_minutes).label("break_minutes"),
    )


_SUM_KEYS = (
    "scheduled",
    "worked",
    "leave",
    "absent",
    "with_check_in",
    "on_time",
    "late_days",
    "early_days",
    "missing_punch",
    "break_over_days",
    "late_minutes",
    "late_minutes_beyond_grace",
    "early_minutes",
    "overrun_minutes",
    "break_minutes",
)


def _rate(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _derive(s: dict, dress: tuple[int, int], employees: int, exceptions: dict) -> dict:
    """KPIs from summed counters. ``dress`` is (observations, compliant)."""
    expected = s["scheduled"] - s["leave"]
    lost = s["late_minutes"] + s["early_minutes"] + s["overrun_minutes"]
    punctuality = _rate(s["on_time"], s["with_check_in"])
    attendance = _rate(s["worked"], expected)
    breaks = _rate(s["worked"] - s["break_over_days"], s["worked"])
    punches = _rate(s["worked"] - s["missing_punch"], s["worked"])
    dress_rate = _rate(dress[1], dress[0])
    parts = [(punctuality, 0.35), (attendance, 0.2), (breaks, 0.2), (punches, 0.1), (dress_rate, 0.15)]
    known = [(v, w) for v, w in parts if v is not None]
    index = round(100 * sum(v * w for v, w in known) / sum(w for _, w in known), 1) if known else None
    return {
        "employees": employees,
        "scheduled_days": s["scheduled"],
        "days_worked": s["worked"],
        "approved_leave_days": s["leave"],
        "unapproved_absences": s["absent"],
        "late_arrivals": s["late_days"],
        "early_departures": s["early_days"],
        "missing_punches": s["missing_punch"],
        "break_overruns": s["break_over_days"],
        "punctuality_rate": punctuality,
        "attendance_rate": attendance,
        "unapproved_absence_rate": _rate(s["absent"], expected),
        "break_compliance_rate": breaks,
        "punch_completeness_rate": punches,
        "avg_break_minutes": round(s["break_minutes"] / s["worked"], 1) if s["worked"] else None,
        "avg_minutes_late_when_late": round(s["late_minutes_beyond_grace"] / s["late_days"], 1)
        if s["late_days"]
        else None,
        "lost_minutes": lost,
        "lost_hours_per_employee_month": round(lost / s["worked"] * WORKING_DAYS_PER_MONTH / 60, 2)
        if s["worked"]
        else None,
        "dress_observations": dress[0],
        "dress_compliance_rate": dress_rate,
        "adherence_index": index,
        "exceptions": exceptions,
    }


def _empty_sums() -> dict:
    return dict.fromkeys(_SUM_KEYS, 0)


def _add(into: dict, row) -> None:
    for k in _SUM_KEYS:
        into[k] += int(getattr(row, k) or 0)


@dataclass
class Window:
    since: date
    until: date  # exclusive

    @property
    def start_dt(self) -> datetime:
        return _midnight(self.since)

    @property
    def end_dt(self) -> datetime:
        return _midnight(self.until)


def window(days: int, today: date) -> Window:
    return Window(today - timedelta(days=days), today + timedelta(days=1))


def _exception_counts(db: Session, cond, win: Window) -> dict:
    counts = dict.fromkeys(("open", "explained", "excused", "confirmed", "dismissed"), 0)
    for status, n in db.execute(
        select(WorkplaceException.status, func.count())
        .where(cond, WorkplaceException.occurred_on >= win.since, WorkplaceException.occurred_on < win.until)
        .group_by(WorkplaceException.status)
    ):
        counts[status] = n
    counts["total"] = sum(counts.values())
    counts["awaiting_decision"] = counts["open"] + counts["explained"]
    return counts


def kpis(
    db: Session, scope: Scope, win: Window, *, unit_ids: set[str] | None = None, employee_id: str | None = None
) -> dict:
    """KPIs for everything in ``scope``, optionally narrowed to org units or one employee."""
    grace = settings_store.get(db, "workplace.grace_minutes")

    def narrow(unit_col, emp_col):
        cond = scope_condition(scope, unit_col, emp_col)
        if unit_ids is not None:
            cond = and_(cond, unit_col.in_(unit_ids))
        if employee_id is not None:
            cond = and_(cond, emp_col == employee_id)
        return cond

    att_cond = narrow(AttendanceDay.org_unit_id, AttendanceDay.employee_id)
    row = db.execute(
        select(*_attendance_sums(grace), func.count(func.distinct(AttendanceDay.employee_id)).label("people")).where(
            att_cond, AttendanceDay.work_date >= win.since, AttendanceDay.work_date < win.until
        )
    ).one()
    sums = _empty_sums()
    _add(sums, row)
    obs_cond = narrow(ConductObservation.org_unit_id, ConductObservation.employee_id)
    dress = db.execute(
        select(
            func.count(ConductObservation.id),
            func.coalesce(func.sum(case((ConductObservation.compliant, 1), else_=0)), 0),
        ).where(obs_cond, ConductObservation.observed_at >= win.start_dt, ConductObservation.observed_at < win.end_dt)
    ).one()
    exc = _exception_counts(db, narrow(WorkplaceException.org_unit_id, WorkplaceException.employee_id), win)
    return _derive(sums, (int(dress[0]), int(dress[1])), int(row.people or 0), exc)


def employee_kpis(db: Session, employee_id: str, days: int = 90, today: date | None = None) -> dict:
    """Pseudonymised workplace KPIs for one employee (safe to include in an AI payload)."""
    today = today or datetime.now(UTC).date()
    win = window(days, today)
    out = kpis(db, Scope(all=True), win, employee_id=employee_id)
    out.pop("employees", None)
    out["by_policy_rule"] = [
        {"rule": code, "name": name, "status": status, "count": n}
        for code, name, status, n in db.execute(
            select(MistakeRule.rule_code, MistakeRule.name, WorkplaceException.status, func.count())
            .join(MistakeRule, MistakeRule.id == WorkplaceException.rule_id)
            .where(WorkplaceException.employee_id == employee_id, WorkplaceException.occurred_on >= win.since)
            .group_by(MistakeRule.rule_code, MistakeRule.name, WorkplaceException.status)
        )
    ]
    out["period_days"] = days
    return out


def daily_series(db: Session, scope: Scope, win: Window, unit_ids: set[str] | None = None) -> list[dict]:
    """Per-day counters; the caller folds them into weeks and weekday patterns."""
    grace = settings_store.get(db, "workplace.grace_minutes")
    cond = scope_condition(scope, AttendanceDay.org_unit_id, AttendanceDay.employee_id)
    if unit_ids is not None:
        cond = and_(cond, AttendanceDay.org_unit_id.in_(unit_ids))
    out = []
    for row in db.execute(
        select(AttendanceDay.work_date, *_attendance_sums(grace))
        .where(cond, AttendanceDay.work_date >= win.since, AttendanceDay.work_date < win.until)
        .group_by(AttendanceDay.work_date)
        .order_by(AttendanceDay.work_date)
    ):
        sums = _empty_sums()
        _add(sums, row)
        out.append({"date": row.work_date, **sums})
    return out


def weekly(series: list[dict]) -> list[dict]:
    buckets: dict[date, dict] = {}
    for day in series:
        week = day["date"] - timedelta(days=day["date"].weekday())
        b = buckets.setdefault(week, _empty_sums())
        for k in _SUM_KEYS:
            b[k] += day[k]
    out = []
    for week in sorted(buckets):
        b = buckets[week]
        out.append(
            {
                "week": week.isoformat(),
                "punctuality_rate": _rate(b["on_time"], b["with_check_in"]),
                "break_compliance_rate": _rate(b["worked"] - b["break_over_days"], b["worked"]),
                "late_arrivals": b["late_days"],
                "lost_minutes": b["late_minutes"] + b["early_minutes"] + b["overrun_minutes"],
                "days_worked": b["worked"],
            }
        )
    return out


def weekday_pattern(series: list[dict]) -> list[dict]:
    late: Counter = Counter()
    seen: Counter = Counter()
    for day in series:
        code = WEEKDAY_CODES[day["date"].weekday()]
        late[code] += day["late_days"]
        seen[code] += day["with_check_in"]
    return [
        {"weekday": code, "late_arrivals": late[code], "late_rate": _rate(late[code], seen[code])}
        for code in ("sat", "sun", "mon", "tue", "wed", "thu")
        if seen[code]
    ]


def by_rule(db: Session, scope: Scope, win: Window, unit_ids: set[str] | None = None) -> list[dict]:
    cond = scope_condition(scope, WorkplaceException.org_unit_id, WorkplaceException.employee_id)
    if unit_ids is not None:
        cond = and_(cond, WorkplaceException.org_unit_id.in_(unit_ids))
    rows: dict[str, dict] = {}
    for code, name, name_ar, category, status, n in db.execute(
        select(
            MistakeRule.rule_code,
            MistakeRule.name,
            MistakeRule.name_ar,
            MistakeRule.category,
            WorkplaceException.status,
            func.count(),
        )
        .join(MistakeRule, MistakeRule.id == WorkplaceException.rule_id)
        .where(cond, WorkplaceException.occurred_on >= win.since, WorkplaceException.occurred_on < win.until)
        .group_by(
            MistakeRule.rule_code,
            MistakeRule.name,
            MistakeRule.name_ar,
            MistakeRule.category,
            WorkplaceException.status,
        )
    ):
        r = rows.setdefault(
            code,
            {"rule_code": code, "name": name, "name_ar": name_ar, "category": category, "total": 0, "by_status": {}},
        )
        r["by_status"][status] = r["by_status"].get(status, 0) + n
        r["total"] += n
    return sorted(rows.values(), key=lambda r: -r["total"])


def reasons(db: Session, scope: Scope, win: Window, unit_ids: set[str] | None = None) -> list[dict]:
    cond = scope_condition(scope, WorkplaceException.org_unit_id, WorkplaceException.employee_id)
    if unit_ids is not None:
        cond = and_(cond, WorkplaceException.org_unit_id.in_(unit_ids))
    return [
        {"reason": reason, "count": n}
        for reason, n in db.execute(
            select(WorkplaceException.reason_code, func.count())
            .where(cond, WorkplaceException.reason_code.is_not(None), WorkplaceException.occurred_on >= win.since)
            .group_by(WorkplaceException.reason_code)
            .order_by(func.count().desc())
        )
    ]


def unit_breakdown(db: Session, scope: Scope, win: Window, children: dict[str, set[str]]) -> dict[str, dict]:
    """KPIs per child unit. ``children`` maps a child unit id to the leaf unit ids it covers."""
    grace = settings_store.get(db, "workplace.grace_minutes")
    leaf_to_child = {leaf: child for child, leaves in children.items() for leaf in leaves}
    sums: dict[str, dict] = {c: _empty_sums() for c in children}
    people: dict[str, set] = defaultdict(set)
    cond = scope_condition(scope, AttendanceDay.org_unit_id, AttendanceDay.employee_id)
    leaves = list(leaf_to_child)
    for row in db.execute(
        select(AttendanceDay.org_unit_id, *_attendance_sums(grace))
        .where(
            cond,
            AttendanceDay.org_unit_id.in_(leaves),
            AttendanceDay.work_date >= win.since,
            AttendanceDay.work_date < win.until,
        )
        .group_by(AttendanceDay.org_unit_id)
    ):
        _add(sums[leaf_to_child[row.org_unit_id]], row)
    for unit_id, emp_id in db.execute(
        select(AttendanceDay.org_unit_id, AttendanceDay.employee_id)
        .where(cond, AttendanceDay.org_unit_id.in_(leaves), AttendanceDay.work_date >= win.since)
        .distinct()
    ):
        people[leaf_to_child[unit_id]].add(emp_id)
    dress: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    obs_cond = scope_condition(scope, ConductObservation.org_unit_id, ConductObservation.employee_id)
    for unit_id, n, ok in db.execute(
        select(ConductObservation.org_unit_id, func.count(), func.sum(case((ConductObservation.compliant, 1), else_=0)))
        .where(obs_cond, ConductObservation.org_unit_id.in_(leaves), ConductObservation.observed_at >= win.start_dt)
        .group_by(ConductObservation.org_unit_id)
    ):
        d = dress[leaf_to_child[unit_id]]
        d[0] += n
        d[1] += int(ok or 0)
    exc: dict[str, Counter] = defaultdict(Counter)
    exc_cond = scope_condition(scope, WorkplaceException.org_unit_id, WorkplaceException.employee_id)
    for unit_id, status, n in db.execute(
        select(WorkplaceException.org_unit_id, WorkplaceException.status, func.count())
        .where(exc_cond, WorkplaceException.org_unit_id.in_(leaves), WorkplaceException.occurred_on >= win.since)
        .group_by(WorkplaceException.org_unit_id, WorkplaceException.status)
    ):
        exc[leaf_to_child[unit_id]][status] += n
    out = {}
    for child in children:
        counts = {s: exc[child].get(s, 0) for s in ("open", "explained", "excused", "confirmed", "dismissed")}
        counts["total"] = sum(counts.values())
        counts["awaiting_decision"] = counts["open"] + counts["explained"]
        out[child] = _derive(sums[child], tuple(dress[child]), len(people[child]), counts)
    return out


def attention_list(
    db: Session, scope: Scope, win: Window, unit_ids: set[str] | None = None, limit: int = 10
) -> list[dict]:
    """Employees with the most confirmed or pending exceptions in the window (for coaching, not sanction)."""
    cond = scope_condition(scope, WorkplaceException.org_unit_id, WorkplaceException.employee_id)
    if unit_ids is not None:
        cond = and_(cond, WorkplaceException.org_unit_id.in_(unit_ids))
    weight = case(
        (WorkplaceException.status == "confirmed", 3),
        (WorkplaceException.status.in_(("open", "explained")), 1),
        else_=0,
    )
    rows = db.execute(
        select(
            WorkplaceException.employee_id,
            func.sum(weight).label("score"),
            func.sum(case((WorkplaceException.status == "confirmed", 1), else_=0)).label("confirmed"),
            func.sum(case((WorkplaceException.status.in_(("open", "explained")), 1), else_=0)).label("pending"),
        )
        .where(cond, WorkplaceException.occurred_on >= win.since)
        .group_by(WorkplaceException.employee_id)
        .order_by(func.sum(weight).desc())
        .limit(limit)
    ).all()
    if not rows:
        return []
    profiles = {
        p.id: p for p in db.scalars(select(EmployeeProfile).where(EmployeeProfile.id.in_([r[0] for r in rows])))
    }
    units = {
        u.id: u for u in db.scalars(select(OrgUnit).where(OrgUnit.id.in_({p.org_unit_id for p in profiles.values()})))
    }
    out = []
    for emp_id, score, confirmed, pending in rows:
        if not score:
            continue
        p = profiles[emp_id]
        u = units.get(p.org_unit_id)
        out.append(
            {
                "employee_id": emp_id,
                "pseudonym": p.pseudonym,
                "role_title": p.role_title,
                "unit": {"id": u.id, "name": u.name, "name_ar": u.name_ar} if u else None,
                "confirmed": int(confirmed or 0),
                "pending": int(pending or 0),
            }
        )
    return out
