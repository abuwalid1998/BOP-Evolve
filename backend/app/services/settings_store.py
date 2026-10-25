"""Runtime-configurable application settings.

Each setting has a typed definition with a default (environment-backed where an
environment variable already exists). Super Admins can override values at
runtime; overrides live in ``app_settings`` and every change is audited.
"""

import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import AppSetting
from app.services import learning


@dataclass(frozen=True)
class SettingDef:
    key: str
    category: str
    kind: str  # int | float | enum | str
    default: object
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple = ()
    max_length: int | None = None


class SettingsError(ValueError):
    def __init__(self, errors: dict[str, dict]):
        super().__init__("Invalid settings")
        self.errors = errors


WEIGHT_KEYS = {
    "learning.weight_understanding": "understanding",
    "learning.weight_action_completion": "action_completion",
    "learning.weight_follow_up": "follow_up",
    "learning.weight_recurrence_trend": "recurrence_trend",
}


def definitions() -> list[SettingDef]:
    env = get_settings()
    d = learning.DEFAULT_CONFIG
    return [
        SettingDef("general.default_locale", "general", "enum", "en", choices=("en", "ar")),
        SettingDef("security.session_ttl_minutes", "general", "int", env.session_ttl_minutes, 15, 1440, 15),
        SettingDef("privacy.min_group_employees", "privacy", "int", env.privacy_min_group_employees, 2, 100, 1),
        SettingDef("privacy.min_group_cases", "privacy", "int", env.privacy_min_group_cases, 1, 10000, 1),
        SettingDef("retention.cases_days", "retention", "int", env.retention_cases_days, 30, 3650, 1),
        SettingDef("retention.audit_days", "retention", "int", env.retention_audit_days, 365, 3650, 1),
        *[SettingDef(key, "learning", "float", d.weights[name], 0, 1, 0.05) for key, name in WEIGHT_KEYS.items()],
        SettingDef("learning.understanding_threshold", "learning", "float", d.understanding_threshold, 0.5, 1, 0.05),
        SettingDef("learning.follow_up_threshold", "learning", "float", d.follow_up_threshold, 0.5, 1, 0.05),
        SettingDef("learning.min_follow_up_cases", "learning", "int", d.min_follow_up_cases, 1, 50, 1),
        SettingDef("learning.follow_up_days", "learning", "int", d.follow_up_days, 30, 365, 1),
        SettingDef("learning.settle_days", "learning", "int", d.settle_days, 0, 120, 1),
        SettingDef("learning.window_days", "learning", "int", d.window_days, 90, 730, 1),
    ]


def _defs() -> dict[str, SettingDef]:
    return {d.key: d for d in definitions()}


def _coerce(d: SettingDef, value):
    if d.kind == "enum":
        if value not in d.choices:
            raise SettingsError({d.key: {"code": "invalid_choice", "choices": list(d.choices)}})
        return value
    if d.kind == "str":
        if not isinstance(value, str):
            raise SettingsError({d.key: {"code": "invalid_type"}})
        if d.max_length and len(value) > d.max_length:
            raise SettingsError({d.key: {"code": "too_long", "max": d.max_length}})
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise SettingsError({d.key: {"code": "invalid_type"}})
    try:
        number = float(value)
    except ValueError as exc:
        raise SettingsError({d.key: {"code": "invalid_type"}}) from exc
    if not math.isfinite(number):
        raise SettingsError({d.key: {"code": "invalid_type"}})
    if d.kind == "int":
        if not number.is_integer():
            raise SettingsError({d.key: {"code": "invalid_type"}})
        number = int(number)
    else:
        number = round(number, 4)
    if (d.minimum is not None and number < d.minimum) or (d.maximum is not None and number > d.maximum):
        raise SettingsError({d.key: {"code": "out_of_range", "min": d.minimum, "max": d.maximum}})
    return number


def overrides(db: Session) -> dict[str, AppSetting]:
    return {row.key: row for row in db.scalars(select(AppSetting))}


def effective(db: Session) -> dict:
    stored = overrides(db)
    values = {}
    for key, d in _defs().items():
        row = stored.get(key)
        value = d.default
        if row is not None:
            try:
                value = _coerce(d, row.value.get("value"))
            except SettingsError:
                value = d.default  # ignore an override that no longer satisfies the definition
        values[key] = value
    return values


def _cross_validate(values: dict) -> dict[str, dict]:
    total = sum(values[k] for k in WEIGHT_KEYS)
    if abs(total - 1) > 0.001:
        return {k: {"code": "weights_sum", "total": round(total, 4)} for k in WEIGHT_KEYS}
    return {}


def update(db: Session, changes: dict, actor_id: str) -> dict[str, tuple]:
    """Validate and store overrides. Returns ``{key: (old, new)}`` for changed keys."""
    defs = _defs()
    errors: dict[str, dict] = {}
    coerced = {}
    for key, value in changes.items():
        d = defs.get(key)
        if d is None:
            errors[key] = {"code": "unknown"}
            continue
        try:
            coerced[key] = _coerce(d, value)
        except SettingsError as exc:
            errors.update(exc.errors)
    if errors:
        raise SettingsError(errors)

    current = effective(db)
    merged = {**current, **coerced}
    cross = _cross_validate(merged)
    if cross:
        raise SettingsError(cross)

    stored = overrides(db)
    changed = {}
    for key, value in coerced.items():
        if current[key] == value and key in stored:
            continue
        changed[key] = (current[key], value)
        row = stored.get(key)
        if row is None:
            db.add(AppSetting(key=key, value={"value": value}, updated_by=actor_id))
        else:
            row.value = {"value": value}
            row.updated_at = utcnow()
            row.updated_by = actor_id
    return changed


def reset(db: Session, key: str) -> dict[str, tuple]:
    """Remove an override. The learning weights only make sense together, so they reset as a group."""
    defs = _defs()
    if key not in defs:
        raise SettingsError({key: {"code": "unknown"}})
    keys = list(WEIGHT_KEYS) if key in WEIGHT_KEYS else [key]
    current = effective(db)
    merged = {**current, **{k: defs[k].default for k in keys}}
    cross = _cross_validate(merged)
    if cross:
        raise SettingsError(cross)
    changed = {}
    for k in keys:
        row = db.get(AppSetting, k)
        if row is not None:
            changed[k] = (current[k], defs[k].default)
            db.delete(row)
    return changed


def get(db: Session, key: str):
    return effective(db)[key]


def learning_config(db: Session) -> learning.LearningConfig:
    v = effective(db)
    return learning.LearningConfig(
        weights={name: v[key] for key, name in WEIGHT_KEYS.items()},
        window_days=v["learning.window_days"],
        follow_up_days=v["learning.follow_up_days"],
        min_follow_up_cases=v["learning.min_follow_up_cases"],
        understanding_threshold=v["learning.understanding_threshold"],
        follow_up_threshold=v["learning.follow_up_threshold"],
        settle_days=v["learning.settle_days"],
    )


def describe(db: Session) -> dict:
    stored = overrides(db)
    values = effective(db)
    return {
        "definitions": [
            {
                "key": d.key,
                "category": d.category,
                "kind": d.kind,
                "default": d.default,
                "min": d.minimum,
                "max": d.maximum,
                "step": d.step,
                "choices": list(d.choices),
                "value": values[d.key],
                "overridden": d.key in stored,
                "updated_at": stored[d.key].updated_at.isoformat() if d.key in stored else None,
            }
            for d in definitions()
        ],
        "learning_method_version": learning_config(db).method_version,
    }
