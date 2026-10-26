"""Rules engine: validate and evaluate rule conditions, and backtest them on history.

A rule's ``conditions`` is ``{"match": "all"|"any", "conditions": [{field, op, value}]}``
over the procedural facts in ``service_cases.attributes``. The same evaluator is used by
the ingestion worker (live detection), the seed (consistent synthetic history) and the
backtest, so a rule behaves identically in all three places.

Backtests and forecasts are aggregate, bank-wide counts on synthetic data. They
estimate workload and impact for the policy owner; they are not a prediction about any
individual employee.
"""

import math
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Finding, ServiceCase
from app.pipeline.catalogue import CASE_TYPES, FIELDS, OPERATORS, WORKPLACE_TYPES, fields_for
from app.services.rbac import Scope

MAX_CONDITIONS = 12
CONFIRMED = {"CONFIRMED", "AMENDED"}
REVIEWED = {"CONFIRMED", "AMENDED", "DISMISSED"}


def all_types() -> list[str]:
    """Rule categories: customer-service case types and workplace-policy record types."""
    return [*CASE_TYPES, *WORKPLACE_TYPES]


def is_workplace(case_type: str) -> bool:
    return case_type in WORKPLACE_TYPES


class RuleError(ValueError):
    """Invalid rule definition. ``errors`` maps a location (e.g. ``conditions.1.value``) to a code."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _option_values(field: dict) -> set[str]:
    return {value for value, *_ in field.get("options", [])}


def validate(case_type: str, definition) -> dict:
    """Return a normalised copy of ``definition`` or raise RuleError."""
    errors: dict[str, str] = {}
    if case_type not in all_types():
        raise RuleError({"category": "unknown_case_type"})
    if not isinstance(definition, dict):
        raise RuleError({"conditions": "invalid"})
    match = definition.get("match", "all")
    if match not in ("all", "any"):
        errors["match"] = "invalid"
    items = definition.get("conditions")
    if not isinstance(items, list) or not items:
        raise RuleError({**errors, "conditions": "required"})
    if len(items) > MAX_CONDITIONS:
        raise RuleError({**errors, "conditions": "too_many"})
    allowed = set(fields_for(case_type))
    clean: list[dict] = []
    for i, item in enumerate(items):
        where = f"conditions.{i}"
        if not isinstance(item, dict):
            errors[where] = "invalid"
            continue
        key, op, value = item.get("field"), item.get("op"), item.get("value")
        field = FIELDS.get(key)
        if field is None:
            errors[f"{where}.field"] = "unknown_field"
            continue
        if key not in allowed:
            errors[f"{where}.field"] = "not_for_case_type"
            continue
        spec = OPERATORS.get(op)
        if spec is None or field["type"] not in spec["types"]:
            errors[f"{where}.op"] = "invalid_operator"
            continue
        if field["type"] == "bool":
            value = None
        elif field["type"] == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                errors[f"{where}.value"] = "number_required"
                continue
            if not field["min"] <= value <= field["max"]:
                errors[f"{where}.value"] = "out_of_range"
                continue
        elif op in ("in", "not_in"):
            if not isinstance(value, list) or not value or not set(value) <= _option_values(field):
                errors[f"{where}.value"] = "invalid_option"
                continue
            value = sorted(set(value))
        elif value not in _option_values(field):
            errors[f"{where}.value"] = "invalid_option"
            continue
        clean.append({"field": key, "op": op, "value": value})
    if errors:
        raise RuleError(errors)
    return {"match": match, "conditions": clean}


def _test(op: str, actual, value) -> bool:
    if actual is None:
        return False  # a missing fact never satisfies a condition
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "in":
        return actual in value
    if op == "not_in":
        return actual not in value
    if op == "gt":
        return actual > value
    if op == "gte":
        return actual >= value
    if op == "lt":
        return actual < value
    if op == "lte":
        return actual <= value
    return False


def evaluate(definition: dict | None, attributes: dict | None) -> tuple[bool, list[dict]]:
    """Return (matched, per-condition detail with the observed fact)."""
    if not definition or not definition.get("conditions"):
        return False, []
    facts = attributes or {}
    detail = [
        {**c, "actual": facts.get(c["field"]), "passed": _test(c["op"], facts.get(c["field"]), c.get("value"))}
        for c in definition["conditions"]
    ]
    passed = [d["passed"] for d in detail]
    matched = all(passed) if definition.get("match", "all") == "all" else any(passed)
    return matched, detail


def matches(definition: dict | None, attributes: dict | None) -> bool:
    return evaluate(definition, attributes)[0]


def matched_detail(definition: dict | None, attributes: dict | None) -> list[dict]:
    """Conditions that held, as stored on a finding."""
    _, detail = evaluate(definition, attributes)
    return [{k: d[k] for k in ("field", "op", "value", "actual")} for d in detail if d["passed"]]


# --------------------------------------------------------------------------- backtest
def _week_start(dt: datetime) -> datetime:
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def _projection(daily_rate: float, days: int, confirm_rate: float | None) -> dict:
    expected = daily_rate * days
    # Poisson approximation for the 95% interval on a count.
    spread = 1.96 * math.sqrt(expected) if expected > 0 else 0.0
    return {
        "days": days,
        "expected": round(expected, 1),
        "low": max(0, math.floor(expected - spread)),
        "high": math.ceil(expected + spread),
        "expected_confirmed": round(expected * confirm_rate, 1) if confirm_rate is not None else None,
    }


def _history(db: Session, case_type: str, since: datetime) -> tuple[list, dict[str, set[str]]]:
    """(rows of (id, occurred_at, facts, org_unit_id, employee_id), finding statuses by row id)."""
    if is_workplace(case_type):
        from app.services import workplace  # workplace builds on this module

        return workplace.history(db, case_type, since)
    rows = db.execute(
        select(
            ServiceCase.id,
            ServiceCase.occurred_at,
            ServiceCase.attributes,
            ServiceCase.org_unit_id,
            ServiceCase.employee_id,
        )
        .where(ServiceCase.case_type == case_type, ServiceCase.occurred_at >= since)
        .order_by(ServiceCase.occurred_at)
    ).all()
    statuses: dict[str, set[str]] = {}
    for case_id, status in db.execute(
        select(Finding.case_id, Finding.status)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(ServiceCase.case_type == case_type, ServiceCase.occurred_at >= since)
    ):
        statuses.setdefault(case_id, set()).add(status)
    return rows, statuses


def backtest(
    db: Session,
    case_type: str,
    definition: dict,
    *,
    days: int = 90,
    compare: dict | None = None,
    sample_scope: Scope | None = None,
    now: datetime | None = None,
) -> dict:
    """Replay ``definition`` over the last ``days`` of cases of ``case_type``.

    Reports how many cases it would have flagged, how that compares with the cases that
    reviewers actually confirmed (a proxy for precision), the weekly trend, a projection
    for the next 30 and 90 days, and - when ``compare`` is given - the overlap with
    another definition (normally the active version of the same rule).
    """
    now = now or utcnow()
    since = now - timedelta(days=days)
    rows, statuses = _history(db, case_type, since)

    total = len(rows)
    evaluated = 0
    matched_ids: list[tuple[str, datetime, str, str]] = []
    compare_ids: set[str] = set()
    weekly: Counter = Counter()
    recent_cutoff = now - timedelta(days=min(28, days))
    recent = 0
    condition_hits: Counter = Counter()
    for case_id, occurred_at, attrs, unit_id, employee_id in rows:
        if attrs is None:
            continue
        evaluated += 1
        hit, detail = evaluate(definition, attrs)
        for i, d in enumerate(detail):
            if d["passed"]:
                condition_hits[i] += 1
        if compare is not None and matches(compare, attrs):
            compare_ids.add(case_id)
        if not hit:
            continue
        matched_ids.append((case_id, occurred_at, unit_id, employee_id))
        weekly[_week_start(occurred_at)] += 1
        if occurred_at >= recent_cutoff:
            recent += 1

    matched_set = {m[0] for m in matched_ids}
    base_confirmed = sum(1 for s in statuses.values() if s & CONFIRMED)
    m_reviewed = sum(1 for cid in matched_set if statuses.get(cid, set()) & REVIEWED)
    m_confirmed = sum(1 for cid in matched_set if statuses.get(cid, set()) & CONFIRMED)
    m_with_finding = sum(1 for cid in matched_set if cid in statuses)
    confirm_rate = m_confirmed / m_reviewed if m_reviewed else None
    base_rate = base_confirmed / evaluated if evaluated else 0.0
    matched_breach_rate = m_confirmed / len(matched_set) if matched_set else 0.0
    lift = round(matched_breach_rate / base_rate, 2) if base_rate and matched_set else None

    series = []
    week = _week_start(since)
    while week <= now:
        series.append({"week": week.date().isoformat(), "matches": weekly.get(week, 0)})
        week += timedelta(days=7)

    recent_days = (now - recent_cutoff).days or 1
    daily_rate = recent / recent_days

    samples = []
    if sample_scope is not None and not sample_scope.empty:
        for case_id, occurred_at, unit_id, employee_id in reversed(matched_ids):
            if sample_scope.all or unit_id in sample_scope.org_unit_ids or employee_id in sample_scope.employee_ids:
                samples.append({"case_id": case_id, "occurred_at": occurred_at.isoformat()})
            if len(samples) == 5:
                break

    result = {
        "case_type": case_type,
        "days": days,
        "cases_evaluated": evaluated,
        "cases_without_facts": total - evaluated,
        "matches": len(matched_set),
        "match_rate": round(len(matched_set) / evaluated, 4) if evaluated else 0.0,
        "matched_with_finding": m_with_finding,
        "matched_reviewed": m_reviewed,
        "matched_confirmed": m_confirmed,
        "confirm_rate": round(confirm_rate, 3) if confirm_rate is not None else None,
        "baseline_confirmed_rate": round(base_rate, 4),
        "lift": lift,
        "condition_hits": [condition_hits.get(i, 0) for i in range(len(definition.get("conditions", [])))],
        "weekly": series,
        "daily_rate": round(daily_rate, 3),
        "forecast": [_projection(daily_rate, 30, confirm_rate), _projection(daily_rate, 90, confirm_rate)],
        "samples": samples,
    }
    if compare is not None:
        result["comparison"] = {
            "current_matches": len(compare_ids),
            "both": len(matched_set & compare_ids),
            "only_proposed": len(matched_set - compare_ids),
            "only_current": len(compare_ids - matched_set),
        }
    return result


def _value_label(field: dict, value, lang: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(_value_label(field, v, lang) or "" for v in value)
    if field["type"] == "bool":
        return ("Yes", "نعم")[lang] if value else ("No", "لا")[lang]
    if field["type"] == "enum":
        for v, en, ar in field.get("options", []):
            if v == value:
                return (en, ar)[lang]
        return str(value)
    unit = field.get("unit")
    return f"{value:,} {unit[lang]}" if unit else f"{value:,}"


def describe(items: list[dict] | None) -> list[dict]:
    """Add EN/AR labels to conditions (or matched-condition records) for display."""
    out = []
    for item in items or []:
        field = FIELDS.get(item.get("field"), {"type": "number", "label": (item.get("field"), item.get("field"))})
        op = OPERATORS.get(item.get("op"), {"label": (item.get("op"), item.get("op"))})
        out.append(
            {
                **item,
                "label": field["label"][0],
                "label_ar": field["label"][1],
                "op_label": op["label"][0],
                "op_label_ar": op["label"][1],
                "value_label": _value_label(field, item.get("value"), 0),
                "value_label_ar": _value_label(field, item.get("value"), 1),
                "actual_label": _value_label(field, item.get("actual"), 0) if "actual" in item else None,
                "actual_label_ar": _value_label(field, item.get("actual"), 1) if "actual" in item else None,
            }
        )
    return out
