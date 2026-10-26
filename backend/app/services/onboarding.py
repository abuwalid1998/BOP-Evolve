"""Onboarding the bank's staff (3,400+ people, from C-level to officers) into BOP Evolve.

1. **Roster import** - HR exports the staff list as CSV. Every row is validated first
   (nothing is written); the preview shows errors, new org units and the access each grade
   will receive. Committing creates or updates accounts by HR employee number.
2. **Access from grade** - the grade and department decide the role and its data scope
   (C-level and directors: their department; regional/branch/section managers: their unit;
   officers: their own records). Everyone also gets the employee self-service role.
3. **Waves** - HR invites people in groups (for example head office, then one region at a
   time). Launching a wave issues one-time activation codes; only their SHA-256 hash is kept.
4. **Journey** - activate with the code and choose a password, pick a language, take the
   guided tour, acknowledge the workplace policies, and pass a short policy quiz.
"""

import csv
import hashlib
import hmac
import io
import random
import re
import secrets
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import new_id, utcnow
from app.models import (
    EmployeeProfile,
    OnboardingImport,
    OnboardingInvite,
    OnboardingProgress,
    OnboardingWave,
    OrgUnit,
    PolicyAcknowledgement,
    PolicyVersion,
    Role,
    User,
    UserRole,
)
from app.pipeline.catalogue import WORKPLACE_POLICIES
from app.services import settings_store, workforce
from app.services.rbac import descendants

# grade -> (label EN, label AR, role, scope level)
GRADES: dict[str, tuple[str, str, str, str]] = {
    "C": ("C-level / Chief officer", "الإدارة التنفيذية العليا", "dept_head", "department"),
    "D": ("Director / Head of department", "مدير دائرة", "dept_head", "department"),
    "RM": ("Regional manager", "مدير إقليم", "regional_manager", "region"),
    "BM": ("Branch manager", "مدير فرع", "branch_manager", "branch"),
    "SM": ("Section / unit head", "رئيس قسم / وحدة", "section_manager", "section"),
    "TL": ("Team lead / senior officer", "قائد فريق / موظف أول", "team_lead", "section"),
    "O": ("Officer", "موظف", "employee", "self"),
    "A": ("Assistant / support staff", "موظف مساند", "employee", "self"),
}
# Departments whose staff get a functional role instead (matched on the department code).
DEPARTMENT_ROLES = {
    "HR": ("hr_chief", "hr_ld"),  # (C/D grades, everyone else); both bank-wide
    "CMP": ("risk_compliance", "risk_compliance"),
    "RISK": ("risk_compliance", "risk_compliance"),
    "AUDIT": ("risk_compliance", "risk_compliance"),
    "IT": ("data_ai_ops", "data_ai_ops"),
}
COLUMNS = (
    "employee_number",
    "full_name",
    "full_name_ar",
    "grade",
    "job_title",
    "department_code",
    "department_name",
    "department_name_ar",
    "region_code",
    "region_name",
    "region_name_ar",
    "branch_code",
    "branch_name",
    "branch_name_ar",
    "section_code",
    "section_name",
    "section_name_ar",
    "manager_employee_number",
    "customer_facing",
    "work_start",
    "work_end",
    "start_date",
    "language",
)
REQUIRED = ("employee_number", "full_name", "grade", "job_title", "department_code")
LEVELS = (("department", "department"), ("region", "region"), ("branch", "branch"), ("section", "section"))
MAX_ROWS = 10000
MAX_ERRORS = 300
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
MAX_ACTIVATION_ATTEMPTS = 5
STEPS = ("activated", "language", "tour", "policies", "quiz")
QUIZ_PASS = 2  # of 3

_NUMBER = re.compile(r"^[A-Za-z0-9-]{2,20}$")
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,39}$")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ImportError_(ValueError):
    pass


# --------------------------------------------------------------------- import
def _clean(value) -> str:
    return (value or "").strip()


def _minutes(value: str, default: int) -> int | None:
    if not value:
        return default
    m = _TIME.match(value)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _department_key(code: str) -> str:
    return code.upper().removeprefix("DEP-").split("-")[0]


def access_for(grade: str, department_code: str) -> tuple[str, str]:
    """(role code, scope level) for a roster row."""
    _, _, role, level = GRADES[grade]
    special = DEPARTMENT_ROLES.get(_department_key(department_code))
    if special:
        return (special[0] if grade in ("C", "D") else special[1]), "global"
    return role, level


def pseudonym_for(employee_number: str) -> str:
    digest = hmac.new(get_settings().jwt_secret.encode(), employee_number.encode(), hashlib.sha256).hexdigest()
    return f"E-{digest[:8].upper()}"


def parse_csv(text: str) -> tuple[list[dict], list[str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        raise ImportError_(f"Missing required columns: {', '.join(missing)}")
    reader.fieldnames = headers
    rows = []
    for i, raw in enumerate(reader, start=2):  # line 1 is the header
        if len(rows) >= MAX_ROWS:
            raise ImportError_(f"The file has more than {MAX_ROWS} rows; split it into several imports")
        if not any(_clean(v) for v in raw.values() if isinstance(v, str)):
            continue
        rows.append({"line": i, **{c: _clean(raw.get(c)) for c in COLUMNS}})
    return rows, headers


def validate(db: Session, rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Return (valid normalised rows, errors, summary). Writes nothing."""
    units = {u.code: u for u in db.scalars(select(OrgUnit))}
    known = set(db.scalars(select(EmployeeProfile.external_ref).where(EmployeeProfile.external_ref.is_not(None))))
    taken_usernames = {
        u for u in db.scalars(select(User.username)) if u not in {r["employee_number"].lower() for r in rows}
    }
    errors: list[dict] = []
    valid: list[dict] = []
    seen: Counter = Counter(r["employee_number"] for r in rows)
    new_units: dict[str, dict] = {}
    numbers = {r["employee_number"] for r in rows} | known

    def err(row, field, code):
        errors.append({"line": row["line"], "employee_number": row["employee_number"], "field": field, "code": code})

    for row in rows:
        before = len(errors)
        number = row["employee_number"]
        for field in REQUIRED:
            if not row[field]:
                err(row, field, "required")
        if number and not _NUMBER.match(number):
            err(row, "employee_number", "invalid")
        if number and seen[number] > 1:
            err(row, "employee_number", "duplicate_in_file")
        if number and number.lower() in taken_usernames and number not in known:
            err(row, "employee_number", "username_taken")
        grade = row["grade"].upper()
        if row["grade"] and grade not in GRADES:
            err(row, "grade", "unknown_grade")
        if row["full_name"] and len(row["full_name"]) > 120:
            err(row, "full_name", "too_long")
        if len(row["job_title"]) > 80:
            err(row, "job_title", "too_long")
        start = _minutes(row["work_start"], 480)
        end = _minutes(row["work_end"], 900)
        if start is None:
            err(row, "work_start", "invalid_time")
        if end is None:
            err(row, "work_end", "invalid_time")
        if start is not None and end is not None and end - start < 180:
            err(row, "work_end", "shift_too_short")
        try:
            start_date = date.fromisoformat(row["start_date"]) if row["start_date"] else None
        except ValueError:
            start_date = None
            err(row, "start_date", "invalid_date")
        customer_facing = row["customer_facing"].lower()
        if customer_facing and customer_facing not in ("yes", "no", "true", "false", "1", "0", "y", "n"):
            err(row, "customer_facing", "invalid")
        language = (row["language"] or "en").lower()
        if language not in ("en", "ar"):
            err(row, "language", "invalid")
        manager = row["manager_employee_number"]
        if manager and (manager == number or manager not in numbers):
            err(row, "manager_employee_number", "unknown_manager")

        # Organisation path: department > region > branch > section (blank levels are skipped).
        path: list[tuple[str, str]] = []
        parent_code = "BANK"
        for column, unit_type in LEVELS:
            code = row[f"{column}_code"].upper()
            if not code:
                continue
            if not _CODE.match(code):
                err(row, f"{column}_code", "invalid")
                break
            existing = units.get(code)
            if existing is not None:
                if existing.unit_type != unit_type:
                    err(row, f"{column}_code", "unit_type_mismatch")
                    break
                parent = units.get(parent_code)
                if parent is not None and existing.parent_id != parent.id:
                    err(row, f"{column}_code", "unit_parent_mismatch")
                    break
            else:
                planned = new_units.get(code)
                if planned is not None and (planned["parent"] != parent_code or planned["type"] != unit_type):
                    err(row, f"{column}_code", "unit_parent_mismatch")
                    break
                if planned is None:
                    new_units[code] = {
                        "code": code,
                        "type": unit_type,
                        "parent": parent_code,
                        "name": row[f"{column}_name"][:120] or code,
                        "name_ar": row[f"{column}_name_ar"][:120] or row[f"{column}_name"][:120] or code,
                    }
            path.append((unit_type, code))
            parent_code = code
        if grade in GRADES and row["department_code"]:
            role, level = access_for(grade, row["department_code"])
            if level not in ("global", "self") and level not in {t for t, _ in path}:
                err(row, f"{level}_code", "required_for_grade")
        else:
            role, level = None, None

        if len(errors) == before:
            valid.append(
                {
                    "employee_number": number,
                    "full_name": row["full_name"],
                    "full_name_ar": row["full_name_ar"] or None,
                    "grade": grade,
                    "job_title": row["job_title"],
                    "path": path,
                    "unit_code": path[-1][1],
                    "manager": manager or None,
                    "customer_facing": customer_facing in ("", "yes", "true", "1", "y"),
                    "work_start_min": start,
                    "work_end_min": end,
                    "start_date": (start_date or utcnow().date()).isoformat(),
                    "language": language,
                    "role": role,
                    "scope_level": level,
                    "exists": number in known,
                }
            )
        if len(errors) > MAX_ERRORS:
            break

    by_role = Counter(r["role"] for r in valid)
    by_grade = Counter(r["grade"] for r in valid)
    by_department = Counter(r["path"][0][1] for r in valid)
    summary = {
        "by_role": dict(by_role.most_common()),
        "by_grade": {g: by_grade.get(g, 0) for g in GRADES if by_grade.get(g)},
        "by_department": dict(by_department.most_common()),
        "new_units": sorted(new_units.values(), key=lambda u: (u["type"], u["code"]))[:500],
        "new_unit_count": len(new_units),
        "to_create": sum(1 for r in valid if not r["exists"]),
        "to_update": sum(1 for r in valid if r["exists"]),
        "customer_facing": sum(1 for r in valid if r["customer_facing"]),
    }
    return valid, errors, summary


def create_import(db: Session, file_name: str, text: str, actor_id: str) -> OnboardingImport:
    rows, _ = parse_csv(text)
    valid, errors, summary = validate(db, rows)
    record = OnboardingImport(
        file_name=file_name[:200] or "roster.csv",
        status="validated" if valid else "failed",
        total_rows=len(rows),
        valid_rows=len(valid),
        error_rows=len({e["line"] for e in errors}),
        errors=errors[:MAX_ERRORS],
        summary=summary,
        rows=valid,
        created_by=actor_id,
    )
    db.add(record)
    db.flush()
    return record


def _ensure_units(db: Session, rows: list[dict], summary: dict) -> dict[str, OrgUnit]:
    units = {u.code: u for u in db.scalars(select(OrgUnit))}
    planned = {u["code"]: u for u in summary.get("new_units", [])}
    for row in rows:
        parent_code = "BANK"
        for unit_type, code in row["path"]:
            if code not in units:
                spec = planned.get(code, {"name": code, "name_ar": code})
                unit = OrgUnit(
                    id=new_id("ORG"),
                    code=code,
                    unit_type=unit_type,
                    name=spec["name"],
                    name_ar=spec["name_ar"],
                    parent_id=units[parent_code].id,
                )
                db.add(unit)
                units[code] = unit
            parent_code = code
    db.flush()
    return units


def commit_import(db: Session, record: OnboardingImport, actor_id: str) -> OnboardingImport:
    """Create or update accounts for every valid row of a validated import."""
    if record.status != "validated":
        raise ImportError_("Only a validated import can be committed")
    rows = record.rows or []
    # Re-check against the current database: the roster may have changed since validation.
    _, errors, _ = validate(db, [{"line": i, **_as_csv_row(r)} for i, r in enumerate(rows, start=2)])
    if errors:
        raise ImportError_("The data changed since this file was validated; upload it again")
    units = _ensure_units(db, rows, record.summary or {})
    roles = {r.code: r.id for r in db.scalars(select(Role))}
    profiles = {
        p.external_ref: p
        for p in db.scalars(
            select(EmployeeProfile).where(EmployeeProfile.external_ref.in_([r["employee_number"] for r in rows]))
        )
    }
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([p.user_id for p in profiles.values()])))}
    created = updated = 0
    # No ORM relationships link these tables, so new rows are written parent-first by hand.
    new_users: list[User] = []
    new_profiles: list[EmployeeProfile] = []
    new_progress: list[OnboardingProgress] = []
    regrant: list[str] = []
    grants: list[UserRole] = []
    for row in rows:
        unit = units[row["unit_code"]]
        scope_unit = None
        if row["scope_level"] not in ("global", "self"):
            scope_unit = units[next(code for t, code in row["path"] if t == row["scope_level"])]
        profile = profiles.get(row["employee_number"])
        if profile is None:
            user = User(
                id=new_id("USR"),
                username=row["employee_number"].lower(),
                display_name=row["full_name"],
                display_name_ar=row["full_name_ar"],
                password_hash=None,
                locale=row["language"],
                status="invited",
            )
            new_users.append(user)
            profile = EmployeeProfile(
                id=new_id("EMP"),
                user_id=user.id,
                pseudonym=pseudonym_for(row["employee_number"]),
                external_ref=row["employee_number"],
                start_date=date.fromisoformat(row["start_date"]),
            )
            new_profiles.append(profile)
            new_progress.append(OnboardingProgress(user_id=user.id))
            profiles[row["employee_number"]] = profile
            created += 1
        else:
            user = users[profile.user_id]
            user.display_name, user.display_name_ar = row["full_name"], row["full_name_ar"]
            regrant.append(user.id)
            updated += 1
        profile.org_unit_id = unit.id
        profile.role_title = row["job_title"][:80]
        profile.grade = row["grade"]
        profile.customer_facing = row["customer_facing"]
        profile.work_start_min, profile.work_end_min = row["work_start_min"], row["work_end_min"]
        grants.append(
            UserRole(
                id=new_id("URL"),
                user_id=user.id,
                role_id=roles[row["role"]],
                scope_type=row["scope_level"],
                scope_id=scope_unit.id if scope_unit else None,
            )
        )
        if row["role"] != "employee":
            grants.append(UserRole(id=new_id("URL"), user_id=user.id, role_id=roles["employee"], scope_type="self"))
    for start in range(0, len(regrant), 900):  # access follows the roster: replace earlier grants
        db.execute(delete(UserRole).where(UserRole.user_id.in_(regrant[start : start + 900])))
    for batch in (new_users, new_profiles, [*new_progress, *grants]):
        db.add_all(batch)
        db.flush()
    for row in rows:
        if row["manager"]:
            profiles[row["employee_number"]].manager_employee_id = profiles[row["manager"]].id
    record.status, record.committed_at = "committed", utcnow()
    record.created_count, record.updated_count = created, updated
    record.rows = None  # the roster is now in the accounts tables; do not keep a second copy
    db.flush()
    return record


def _as_csv_row(r: dict) -> dict:
    path = dict(r["path"])
    out = {c: "" for c in COLUMNS}
    out.update(
        {
            "employee_number": r["employee_number"],
            "full_name": r["full_name"],
            "full_name_ar": r["full_name_ar"] or "",
            "grade": r["grade"],
            "job_title": r["job_title"],
            "manager_employee_number": r["manager"] or "",
            "customer_facing": "yes" if r["customer_facing"] else "no",
            "work_start": f"{r['work_start_min'] // 60:02d}:{r['work_start_min'] % 60:02d}",
            "work_end": f"{r['work_end_min'] // 60:02d}:{r['work_end_min'] % 60:02d}",
            "start_date": r["start_date"],
            "language": r["language"],
        }
    )
    for column, unit_type in LEVELS:
        out[f"{column}_code"] = path.get(unit_type, "")
    return out


# ---------------------------------------------------------------------- waves
def _wave_users(db: Session, criteria: dict):
    """Imported accounts matching a wave's criteria (grades, unit subtrees)."""
    stmt = (
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(EmployeeProfile.external_ref.is_not(None))
    )
    if criteria.get("grades"):
        stmt = stmt.where(EmployeeProfile.grade.in_(criteria["grades"]))
    if criteria.get("unit_ids"):
        stmt = stmt.where(EmployeeProfile.org_unit_id.in_(descendants(db, set(criteria["unit_ids"]))))
    return stmt


def wave_candidates(db: Session, criteria: dict) -> dict:
    stmt = _wave_users(db, criteria).where(User.status == "invited")
    rows = db.execute(stmt).all()
    return {"count": len(rows), "by_grade": dict(Counter(p.grade for _, p in rows).most_common())}


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def code_hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().upper().encode()).hexdigest()


def launch_wave(db: Session, wave: OnboardingWave, actor_id: str) -> list[dict]:
    """Issue activation codes for everyone in the wave who has not activated yet. Codes are returned once."""
    now = utcnow()
    ttl = settings_store.get(db, "onboarding.code_ttl_days")
    rows = db.execute(_wave_users(db, wave.criteria).where(User.status == "invited")).all()
    user_ids = [u.id for u, _ in rows]
    for start in range(0, len(user_ids), 900):
        chunk = user_ids[start : start + 900]
        for invite in db.scalars(
            select(OnboardingInvite).where(
                OnboardingInvite.user_id.in_(chunk),
                OnboardingInvite.used_at.is_(None),
                OnboardingInvite.revoked_at.is_(None),
            )
        ):
            invite.revoked_at = now
    progress = {}
    for start in range(0, len(user_ids), 900):
        for p in db.scalars(
            select(OnboardingProgress).where(OnboardingProgress.user_id.in_(user_ids[start : start + 900]))
        ):
            progress[p.user_id] = p
    issued = []
    expires = now + timedelta(days=ttl)
    for user, profile in rows:
        code = new_code()
        db.add(
            OnboardingInvite(
                user_id=user.id, wave_id=wave.id, code_hash=code_hash(code), expires_at=expires, created_by=actor_id
            )
        )
        p = progress.get(user.id)
        if p is None:
            p = OnboardingProgress(user_id=user.id)
            db.add(p)
        p.wave_id, p.invited_at = wave.id, now
        issued.append(
            {
                "employee_number": profile.external_ref,
                "username": user.username,
                "name": user.display_name,
                "grade": profile.grade,
                "activation_code": code,
                "expires_at": expires.date().isoformat(),
            }
        )
    wave.status, wave.launched_at, wave.launched_by = "launched", now, actor_id
    wave.employee_count = (wave.employee_count or 0) + len(issued)
    db.flush()
    return issued


def codes_csv(issued: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=["employee_number", "username", "name", "grade", "activation_code", "expires_at"]
    )
    writer.writeheader()
    writer.writerows(issued)
    return out.getvalue()


class ActivationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def activate(db: Session, username: str, code: str, password: str) -> User:
    """Set the first password with a valid activation code."""
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or user.status != "invited":
        raise ActivationError("invalid_code")
    invites = list(
        db.scalars(
            select(OnboardingInvite).where(
                OnboardingInvite.user_id == user.id,
                OnboardingInvite.used_at.is_(None),
                OnboardingInvite.revoked_at.is_(None),
            )
        )
    )
    now = utcnow()
    live = [i for i in invites if i.expires_at > now]
    if not live:
        raise ActivationError("expired" if invites else "invalid_code")
    digest = code_hash(code)
    match = next((i for i in live if hmac.compare_digest(i.code_hash, digest)), None)
    if match is None:
        for i in live:
            i.failed_attempts += 1
            if i.failed_attempts >= MAX_ACTIVATION_ATTEMPTS:
                i.revoked_at = now
        db.flush()
        raise ActivationError("invalid_code")
    from app.services.security import hash_password

    match.used_at = now
    user.password_hash = hash_password(password)
    user.status = "active"
    progress = db.scalar(select(OnboardingProgress).where(OnboardingProgress.user_id == user.id))
    if progress is None:
        progress = OnboardingProgress(user_id=user.id)
        db.add(progress)
    progress.activated_at = now
    db.flush()
    return user


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "too_short"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "needs_letters_and_digits"
    return None


# -------------------------------------------------------------------- journey
def progress_for(db: Session, user: User) -> OnboardingProgress:
    p = db.scalar(select(OnboardingProgress).where(OnboardingProgress.user_id == user.id))
    if p is None:
        # Accounts created before onboarding existed start the journey already activated.
        p = OnboardingProgress(user_id=user.id, activated_at=user.created_at or utcnow())
        db.add(p)
        db.flush()
    return p


def required_policies(db: Session, employee: EmployeeProfile | None) -> list[PolicyVersion]:
    """Workplace policies for everyone; customer-facing staff also acknowledge the service policies."""
    rows = list(
        db.scalars(
            select(PolicyVersion)
            .where(PolicyVersion.policy_code.in_(WORKPLACE_POLICIES), PolicyVersion.status == "active")
            .order_by(PolicyVersion.policy_code)
        )
    )
    if employee is not None and employee.customer_facing:
        seen = {p.id for p in rows}
        for policy in sorted(workforce.active_policies(db).values(), key=lambda p: p.policy_code):
            if policy.id not in seen and policy.policy_code not in WORKPLACE_POLICIES:
                rows.append(policy)
                seen.add(policy.id)
    return rows


def acknowledged(db: Session, user_id: str) -> set[str]:
    return set(
        db.scalars(select(PolicyAcknowledgement.policy_version_id).where(PolicyAcknowledgement.user_id == user_id))
    )


def refresh_completion(p: OnboardingProgress) -> None:
    if p.completed_at is None and all(
        (p.activated_at, p.language_set_at, p.tour_done_at, p.policies_ack_at, p.quiz_passed_at)
    ):
        p.completed_at = utcnow()


def stage(p: OnboardingProgress | None, status: str) -> str:
    if p is None or (p.invited_at is None and status == "invited"):
        return "not_invited"
    if p.completed_at:
        return "completed"
    if not p.activated_at:
        return "invited"
    if any((p.language_set_at, p.tour_done_at, p.policies_ack_at, p.quiz_passed_at)):
        return "in_progress"
    return "activated"


def static_quiz(allowance: int, language: str) -> dict:
    """Built-in quiz used when the AI assistant is off or unavailable."""
    ar = language == "ar"
    options = sorted({30, 45, allowance, 90} | ({120} if allowance in (30, 45, 90) else set()))[:4]
    if allowance not in options:
        options[-1] = allowance
    questions = [
        {
            "question": "ما الحد اليومي المسموح للاستراحات؟" if ar else "What is the daily break allowance?",
            "options": [f"{m} دقيقة" if ar else f"{m} minutes" for m in options],
            "answer_index": options.index(allowance),
            "explanation": f"ينص الإجراء HR-02 على {allowance} دقيقة يومياً."
            if ar
            else f"Policy HR-02 sets a {allowance}-minute daily allowance.",
        },
        {
            "question": "نسيت تسجيل الخروج أمس. ماذا تفعل؟"
            if ar
            else "You forgot to check out yesterday. What should you do?",
            "options": [
                "لا شيء، سيُصحَّح تلقائياً" if ar else "Nothing, it corrects itself",
                "أصحّحه مع مديري المباشر في أقرب وقت" if ar else "Correct it with my line manager as soon as possible",
                "أسجّل خروجاً متأخراً اليوم" if ar else "Check out later today to make up for it",
                "أطلب من زميل التسجيل عني" if ar else "Ask a colleague to record it for me",
            ],
            "answer_index": 1,
            "explanation": "يتطلب الإجراء HR-01 تصحيح التسجيل المفقود مع المدير المباشر."
            if ar
            else "Policy HR-01 requires a missing record to be corrected with the line manager.",
        },
        {
            "question": "ما الذي يجب إظهاره طوال وقت العمل؟" if ar else "What must be displayed at all times at work?",
            "options": [
                "بطاقة الموظف" if ar else "Your staff ID badge",
                "جدول الاستراحات" if ar else "Your break schedule",
                "الهاتف المحمول" if ar else "Your mobile phone",
                "لا شيء" if ar else "Nothing",
            ],
            "answer_index": 0,
            "explanation": "يتطلب الإجراء HR-03 إظهار بطاقة الموظف في جميع الأوقات."
            if ar
            else "Policy HR-03 requires the staff ID badge to be displayed at all times.",
        },
    ]
    return {"questions": questions}


def valid_quiz(output: dict | None) -> bool:
    try:
        qs = output["questions"]
        return (
            isinstance(qs, list)
            and len(qs) == 3
            and all(
                isinstance(q.get("question"), str)
                and isinstance(q.get("options"), list)
                and len(q["options"]) == 4
                and all(isinstance(o, str) for o in q["options"])
                and isinstance(q.get("answer_index"), int)
                and 0 <= q["answer_index"] <= 3
                for q in qs
            )
        )
    except (KeyError, TypeError, AttributeError):
        return False


def public_quiz(quiz: dict) -> list[dict]:
    """Questions without the answers."""
    return [{"question": q["question"], "options": q["options"]} for q in quiz["questions"]]


# ------------------------------------------------------------------- overview
def overview(db: Session) -> dict:
    roster = db.execute(
        select(User.status, OnboardingProgress, EmployeeProfile.org_unit_id, EmployeeProfile.grade)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .outerjoin(OnboardingProgress, OnboardingProgress.user_id == User.id)
        .where(EmployeeProfile.external_ref.is_not(None))
    ).all()
    units, chains = workforce.unit_chain(db)

    def department(unit_id):
        for uid in chains.get(unit_id, []):
            if units[uid].unit_type == "department":
                return units[uid]
        return None

    funnel = Counter()
    by_stage = Counter()
    by_department: dict[str, Counter] = {}
    by_grade: dict[str, Counter] = {}
    daily = Counter()
    since = utcnow() - timedelta(days=30)
    for status, p, unit_id, grade in roster:
        s = stage(p, status)
        by_stage[s] += 1
        funnel["roster"] += 1
        if p is not None:
            for key, value in (
                ("invited", p.invited_at),
                ("activated", p.activated_at),
                ("language", p.language_set_at),
                ("tour", p.tour_done_at),
                ("policies", p.policies_ack_at),
                ("quiz", p.quiz_passed_at),
                ("completed", p.completed_at),
            ):
                if value:
                    funnel[key] += 1
            if p.activated_at and p.activated_at >= since:
                daily[p.activated_at.date().isoformat()] += 1
        dept = department(unit_id)
        key = dept.id if dept else "-"
        by_department.setdefault(key, Counter())[s] += 1
        by_grade.setdefault(grade or "-", Counter())[s] += 1
    waves = []
    for wave in db.scalars(select(OnboardingWave).order_by(OnboardingWave.starts_on, OnboardingWave.created_at)):
        counts = Counter()
        for p, status in db.execute(
            select(OnboardingProgress, User.status)
            .join(User, User.id == OnboardingProgress.user_id)
            .where(OnboardingProgress.wave_id == wave.id)
        ):
            counts[stage(p, status)] += 1
        waves.append(
            {**wave_ref(wave), "stages": dict(counts), "candidates": wave_candidates(db, wave.criteria)["count"]}
        )
    today = utcnow().date()
    return {
        "funnel": {
            k: funnel.get(k, 0)
            for k in ("roster", "invited", "activated", "language", "tour", "policies", "quiz", "completed")
        },
        "by_stage": dict(by_stage),
        "by_department": [
            {
                "unit": {"id": units[k].id, "code": units[k].code, "name": units[k].name, "name_ar": units[k].name_ar}
                if k in units
                else None,
                "stages": dict(v),
                "total": sum(v.values()),
            }
            for k, v in sorted(by_department.items(), key=lambda kv: -sum(kv[1].values()))
        ],
        "by_grade": [
            {
                "grade": g,
                "label": GRADES.get(g, (g, g))[0],
                "label_ar": GRADES.get(g, (g, g))[1],
                "stages": dict(v),
                "total": sum(v.values()),
            }
            for g, v in sorted(by_grade.items(), key=lambda kv: list(GRADES).index(kv[0]) if kv[0] in GRADES else 99)
        ],
        "daily_activations": [
            {
                "date": (today - timedelta(days=i)).isoformat(),
                "count": daily.get((today - timedelta(days=i)).isoformat(), 0),
            }
            for i in range(29, -1, -1)
        ],
        "waves": waves,
        "imports": [
            import_ref(i)
            for i in db.scalars(select(OnboardingImport).order_by(OnboardingImport.created_at.desc()).limit(10))
        ],
        "grades": [
            {"code": g, "label": v[0], "label_ar": v[1], "role": v[2], "scope": v[3]} for g, v in GRADES.items()
        ],
    }


def wave_ref(wave: OnboardingWave) -> dict:
    return {
        "id": wave.id,
        "name": wave.name,
        "description": wave.description,
        "criteria": wave.criteria,
        "starts_on": wave.starts_on.isoformat(),
        "status": wave.status,
        "employee_count": wave.employee_count,
        "launched_at": wave.launched_at.isoformat() if wave.launched_at else None,
        "reminder_message": wave.reminder_message,
        "reminder_message_ar": wave.reminder_message_ar,
    }


def import_ref(record: OnboardingImport, *, detail: bool = False) -> dict:
    out = {
        "id": record.id,
        "file_name": record.file_name,
        "status": record.status,
        "total_rows": record.total_rows,
        "valid_rows": record.valid_rows,
        "error_rows": record.error_rows,
        "created_count": record.created_count,
        "updated_count": record.updated_count,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "committed_at": record.committed_at.isoformat() if record.committed_at else None,
    }
    if detail:
        out["errors"] = record.errors or []
        out["summary"] = record.summary or {}
        out["preview"] = [
            {
                k: r[k]
                for k in (
                    "employee_number",
                    "full_name",
                    "grade",
                    "job_title",
                    "unit_code",
                    "role",
                    "scope_level",
                    "exists",
                )
            }
            for r in (record.rows or [])[:25]
        ]
    return out


# -------------------------------------------------------------- sample roster
FIRST_NAMES = [
    ("Ahmad", "أحمد"),
    ("Mohammad", "محمد"),
    ("Omar", "عمر"),
    ("Khaled", "خالد"),
    ("Yousef", "يوسف"),
    ("Ibrahim", "إبراهيم"),
    ("Rami", "رامي"),
    ("Sami", "سامي"),
    ("Tareq", "طارق"),
    ("Nour", "نور"),
    ("Hadi", "هادي"),
    ("Basel", "باسل"),
    ("Anas", "أنس"),
    ("Mahmoud", "محمود"),
    ("Firas", "فراس"),
    ("Layla", "ليلى"),
    ("Rania", "رانيا"),
    ("Dina", "دينا"),
    ("Hala", "هالة"),
    ("Sara", "سارة"),
    ("Maryam", "مريم"),
    ("Lina", "لينا"),
    ("Reem", "ريم"),
    ("Yasmin", "ياسمين"),
    ("Aya", "آية"),
    ("Noor", "نور"),
    ("Hiba", "هبة"),
    ("Salma", "سلمى"),
    ("Dana", "دانة"),
    ("Rula", "رلى"),
]
FAMILY_NAMES = [
    ("Haddad", "حداد"),
    ("Khalil", "خليل"),
    ("Saleh", "صالح"),
    ("Nasser", "ناصر"),
    ("Odeh", "عودة"),
    ("Hamdan", "حمدان"),
    ("Mansour", "منصور"),
    ("Qasem", "قاسم"),
    ("Barghouti", "برغوثي"),
    ("Shaheen", "شاهين"),
    ("Abed", "عابد"),
    ("Darwish", "درويش"),
    ("Jaber", "جابر"),
    ("Masri", "مصري"),
    ("Zaid", "زيد"),
    ("Hijazi", "حجازي"),
    ("Awad", "عوض"),
    ("Salem", "سالم"),
    ("Yaseen", "ياسين"),
    ("Najjar", "نجار"),
    ("Khoury", "خوري"),
    ("Issa", "عيسى"),
    ("Sabbah", "صباح"),
    ("Ghanem", "غانم"),
    ("Amro", "عمرو"),
]
SAMPLE_REGIONS = [
    ("NORTH", "North", "الشمال", 18),
    ("CENTRAL", "Central", "الوسط", 24),
    ("SOUTH", "South", "الجنوب", 16),
    ("GAZA", "Gaza", "غزة", 12),
]
SAMPLE_HQ = [
    (
        "DEP-HR",
        "Human Resources",
        "الموارد البشرية",
        [
            ("HRBP", "HR Business Partners", "شركاء الموارد البشرية", 22),
            ("LD", "Learning & Development", "التعلم والتطوير", 18),
        ],
    ),
    (
        "DEP-IT",
        "Information Technology",
        "تكنولوجيا المعلومات",
        [("APP", "Applications", "التطبيقات", 45), ("INF", "Infrastructure", "البنية التحتية", 35)],
    ),
    (
        "DEP-FIN",
        "Finance",
        "المالية",
        [("ACC", "Accounting", "المحاسبة", 40), ("CTL", "Financial Control", "الرقابة المالية", 20)],
    ),
    (
        "DEP-OPS",
        "Operations & Policy",
        "العمليات والسياسات",
        [("CEN", "Central Operations", "العمليات المركزية", 90), ("PAY", "Payments", "المدفوعات", 50)],
    ),
    (
        "DEP-CMP",
        "Risk & Compliance",
        "المخاطر والامتثال",
        [("AML", "AML & Sanctions", "مكافحة غسل الأموال", 30), ("AUD", "Internal Audit", "التدقيق الداخلي", 25)],
    ),
    (
        "DEP-CORP",
        "Corporate Banking",
        "الخدمات المصرفية للشركات",
        [("RM", "Relationship Management", "إدارة العلاقات", 60), ("CRD", "Credit", "الائتمان", 40)],
    ),
    ("DEP-TRS", "Treasury", "الخزينة", [("FX", "Dealing Room", "غرفة التداول", 18)]),
]


def sample_roster(size: int = 3400, seed: int = 3400) -> str:
    """A synthetic Bank-of-Palestine-sized roster (fictional people) for trying the import."""
    rng = random.Random(seed)
    rows: list[dict] = []
    number = 100001

    def person(grade, title, path, manager=None, customer_facing=False, start="08:00", end="15:00"):
        nonlocal number
        first, family = rng.choice(FIRST_NAMES), rng.choice(FAMILY_NAMES)
        middle = rng.choice(FIRST_NAMES[:15])
        row = {c: "" for c in COLUMNS}
        row.update(
            {
                "employee_number": str(number),
                "full_name": f"{first[0]} {middle[0]} {family[0]}",
                "full_name_ar": f"{first[1]} {middle[1]} {family[1]}",
                "grade": grade,
                "job_title": title,
                "manager_employee_number": manager or "",
                "customer_facing": "yes" if customer_facing else "no",
                "work_start": start,
                "work_end": end,
                "start_date": date(rng.randint(2005, 2026), rng.randint(1, 12), 1).isoformat()
                if rng.random() > 0.04
                else (utcnow().date() + timedelta(days=rng.randint(-10, 20))).isoformat(),
                "language": "ar" if rng.random() < 0.7 else "en",
            }
        )
        row.update(path)
        rows.append(row)
        number += 1
        return row["employee_number"]

    def unit(column, code, name, name_ar):
        return {f"{column}_code": code, f"{column}_name": name, f"{column}_name_ar": name_ar}

    retail = unit("department", "DEP-RETAIL", "Retail Banking", "الخدمات المصرفية للأفراد")
    ceo = person(
        "C", "Chief Executive Officer", unit("department", "DEP-OPS", "Operations & Policy", "العمليات والسياسات")
    )
    retail_head = person("C", "Chief Retail Officer", retail, ceo)
    for code, name, name_ar, sections in SAMPLE_HQ:
        dept = unit("department", code, name, name_ar)
        head = person("C" if code in ("DEP-HR", "DEP-CMP", "DEP-FIN") else "D", f"Head of {name}", dept, ceo)
        for scode, sname, sname_ar, staff in sections:
            path = {**dept, **unit("section", f"{code}-{scode}", f"{name} · {sname}", f"{name_ar} · {sname_ar}")}
            sm = person("SM", f"{sname} Manager", path, head)
            tl = person("TL", f"Senior {sname} Officer", path, sm)
            for _ in range(staff):
                person(rng.choice(["O"] * 6 + ["A"]), f"{sname} Officer", path, tl)
    cc = unit("department", "DEP-CC", "Contact Centre", "مركز الاتصال")
    cc_head = person("D", "Head of Contact Centre", cc, retail_head)
    for scode, sname, sname_ar, staff in (
        ("VOICE", "Inbound Voice", "الاتصال الهاتفي", 120),
        ("CHAT", "Digital Chat", "المحادثة الرقمية", 60),
    ):
        path = {**cc, **unit("section", f"CC-{scode}", f"Contact Centre · {sname}", f"مركز الاتصال · {sname_ar}")}
        sm = person("SM", f"{sname} Manager", path, cc_head, True, "09:00", "17:00")
        leads = [person("TL", f"{sname} Team Lead", path, sm, True, "09:00", "17:00") for _ in range(staff // 15)]
        for i in range(staff):
            person(
                "O",
                "Contact Centre Agent" if scode == "VOICE" else "Digital Service Agent",
                path,
                leads[i % len(leads)],
                True,
                "09:00",
                "17:00",
            )
    branches = []
    for rcode, rname, rname_ar, count in SAMPLE_REGIONS:
        region = {**retail, **unit("region", f"REG-{rcode}", f"{rname} Region", f"إقليم {rname_ar}")}
        rm = person("RM", f"{rname} Regional Manager", region, retail_head)
        for i in range(1, count + 1):
            bcode = f"BR-{rcode[0]}{i:02d}"
            branch = {**region, **unit("branch", bcode, f"{rname} Branch {i:02d}", f"فرع {rname_ar} {i:02d}")}
            bm = person("BM", "Branch Manager", branch, rm, True)
            branches.append((branch, bm, bcode, rname, rname_ar, i))
    # Fill the branches until the roster reaches ``size`` people.
    sections = (
        ("TEL", "Tellers", "الصرّافون", "Teller"),
        ("CSO", "Customer Service", "خدمة العملاء", "Customer Service Officer"),
    )
    section_leads = []
    for branch, bm, bcode, rname, rname_ar, i in branches:
        for scode, sname, sname_ar, title in sections:
            path = {
                **branch,
                **unit(
                    "section",
                    f"{bcode}-{scode}",
                    f"{rname} Branch {i:02d} · {sname}",
                    f"فرع {rname_ar} {i:02d} · {sname_ar}",
                ),
            }
            sm = person("SM", f"{sname} Supervisor", path, bm, True)
            tl = person("TL", f"Senior {title}", path, sm, True)
            section_leads.append((path, tl, title))
    k = 0
    while len(rows) < size:
        path, tl, title = section_leads[k % len(section_leads)]
        person("O", title, path, tl, True)
        k += 1
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(COLUMNS))
    writer.writeheader()
    writer.writerows(rows[:size] if len(rows) > size else rows)
    return out.getvalue()


def wave_funnel(db: Session, wave_id: str) -> dict:
    """Aggregate counts for one wave (used by the AI reminder draft; no individuals)."""
    stages = Counter()
    stuck = Counter()
    for p, status in db.execute(
        select(OnboardingProgress, User.status)
        .join(User, User.id == OnboardingProgress.user_id)
        .where(OnboardingProgress.wave_id == wave_id)
    ):
        s = stage(p, status)
        stages[s] += 1
        if s in ("activated", "in_progress"):
            for step, value in (
                ("language", p.language_set_at),
                ("tour", p.tour_done_at),
                ("policies", p.policies_ack_at),
                ("quiz", p.quiz_passed_at),
            ):
                if not value:
                    stuck[step] += 1
                    break
    return {"by_stage": dict(stages), "next_step_pending": dict(stuck)}


def count_roster(db: Session) -> int:
    return (
        db.scalar(select(func.count()).select_from(EmployeeProfile).where(EmployeeProfile.external_ref.is_not(None)))
        or 0
    )
