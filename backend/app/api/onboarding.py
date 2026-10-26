"""Onboarding the bank's staff: roster import, waves, activation codes and the welcome journey."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, require
from app.db import get_db, utcnow
from app.models import (
    AIGeneration,
    EmployeeProfile,
    OnboardingImport,
    OnboardingProgress,
    OnboardingWave,
    OrgUnit,
    PolicyAcknowledgement,
    User,
)
from app.services import ai, audit, onboarding, settings_store
from app.services.rbac import descendants

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

MANAGE = "onboarding.manage"
Lang = Literal["en", "ar"]


def _iso(value):
    return value.isoformat() if value else None


# --------------------------------------------------------------------- import
class ImportBody(BaseModel):
    file_name: str = Field(default="roster.csv", max_length=200)
    content: str = Field(min_length=10, max_length=8_000_000)


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def validate_import(body: ImportBody, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    """Validate a roster CSV. Nothing is written to the accounts tables until it is committed."""
    try:
        record = onboarding.create_import(db, body.file_name, body.content, principal.user.id)
    except onboarding.ImportError_ as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "invalid_file", "message": str(exc)}
        ) from exc
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.import.validated",
        resource_type="onboarding_import",
        resource_id=record.id,
        request_id=principal.request_id,
        metadata={"rows": record.total_rows, "valid": record.valid_rows, "errors": record.error_rows},
    )
    db.commit()
    return onboarding.import_ref(record, detail=True)


@router.get("/imports/{import_id}")
def get_import(import_id: str, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    record = db.get(OnboardingImport, import_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return onboarding.import_ref(record, detail=True)


@router.post("/imports/{import_id}/commit")
def commit_import(import_id: str, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    record = db.get(OnboardingImport, import_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    try:
        onboarding.commit_import(db, record, principal.user.id)
    except onboarding.ImportError_ as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "cannot_commit", "message": str(exc)}) from exc
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.import.committed",
        resource_type="onboarding_import",
        resource_id=record.id,
        request_id=principal.request_id,
        metadata={"created": record.created_count, "updated": record.updated_count},
    )
    db.commit()
    return onboarding.import_ref(record, detail=True)


@router.get("/sample-roster")
def sample_roster(size: int = Query(3400, ge=10, le=6000), principal: Principal = Depends(require(MANAGE))):
    """A synthetic roster of fictional people, shaped like the bank, for trying the import."""
    return Response(
        onboarding.sample_roster(size),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bop-evolve-sample-roster-{size}.csv"'},
    )


# -------------------------------------------------------------------- overview
@router.get("/overview")
def overview(principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    return onboarding.overview(db)


STAGES = ("not_invited", "invited", "activated", "in_progress", "completed")


@router.get("/people")
def people(
    stage: Literal[STAGES] | None = None,  # type: ignore[valid-type]
    wave_id: str | None = None,
    unit_id: str | None = None,
    grade: str | None = None,
    q: str | None = Query(None, max_length=60),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
):
    p = OnboardingProgress
    cond = EmployeeProfile.external_ref.is_not(None)
    if wave_id:
        cond = and_(cond, p.wave_id == wave_id)
    if unit_id:
        cond = and_(cond, EmployeeProfile.org_unit_id.in_(descendants(db, {unit_id})))
    if grade:
        cond = and_(cond, EmployeeProfile.grade == grade)
    if q:
        needle = f"%{q.strip()}%"
        cond = and_(
            cond,
            or_(
                User.display_name.ilike(needle),
                User.display_name_ar.ilike(needle),
                EmployeeProfile.external_ref.ilike(needle),
                EmployeeProfile.role_title.ilike(needle),
            ),
        )
    if stage == "not_invited":
        cond = and_(cond, User.status == "invited", or_(p.id.is_(None), p.invited_at.is_(None)))
    elif stage == "invited":
        cond = and_(cond, p.invited_at.is_not(None), p.activated_at.is_(None))
    elif stage == "activated":
        cond = and_(
            cond,
            p.activated_at.is_not(None),
            p.completed_at.is_(None),
            p.language_set_at.is_(None),
            p.tour_done_at.is_(None),
            p.policies_ack_at.is_(None),
            p.quiz_passed_at.is_(None),
        )
    elif stage == "in_progress":
        cond = and_(
            cond,
            p.activated_at.is_not(None),
            p.completed_at.is_(None),
            or_(
                p.language_set_at.is_not(None),
                p.tour_done_at.is_not(None),
                p.policies_ack_at.is_not(None),
                p.quiz_passed_at.is_not(None),
            ),
        )
    elif stage == "completed":
        cond = and_(cond, p.completed_at.is_not(None))
    base = (
        select(User, EmployeeProfile, p, OrgUnit)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .join(OrgUnit, OrgUnit.id == EmployeeProfile.org_unit_id)
        .outerjoin(p, p.user_id == User.id)
        .where(cond)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(base.order_by(EmployeeProfile.external_ref).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for user, profile, progress, unit in rows:
        items.append(
            {
                "user_id": user.id,
                "employee_number": profile.external_ref,
                "name": user.display_name,
                "name_ar": user.display_name_ar,
                "grade": profile.grade,
                "job_title": profile.role_title,
                "unit": {"id": unit.id, "code": unit.code, "name": unit.name, "name_ar": unit.name_ar},
                "stage": onboarding.stage(progress, user.status),
                "steps": {
                    "invited": _iso(progress.invited_at) if progress else None,
                    "activated": _iso(progress.activated_at) if progress else None,
                    "language": _iso(progress.language_set_at) if progress else None,
                    "tour": _iso(progress.tour_done_at) if progress else None,
                    "policies": _iso(progress.policies_ack_at) if progress else None,
                    "quiz": _iso(progress.quiz_passed_at) if progress else None,
                    "completed": _iso(progress.completed_at) if progress else None,
                },
                "reminders_sent": progress.reminders_sent if progress else 0,
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/units")
def units(principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    """Org units for choosing a wave's scope."""
    return [
        {
            "id": u.id,
            "code": u.code,
            "type": u.unit_type,
            "name": u.name,
            "name_ar": u.name_ar,
            "parent_id": u.parent_id,
        }
        for u in db.scalars(select(OrgUnit).where(OrgUnit.active.is_(True)).order_by(OrgUnit.code))
    ]


# ---------------------------------------------------------------------- waves
class WaveBody(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    grades: list[str] = Field(default_factory=list, max_length=8)
    unit_ids: list[str] = Field(default_factory=list, max_length=200)
    starts_on: date


def _criteria(db: Session, body: WaveBody) -> dict:
    bad = [g for g in body.grades if g not in onboarding.GRADES]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": {"grades": "unknown_grade"}})
    if body.unit_ids:
        found = set(db.scalars(select(OrgUnit.id).where(OrgUnit.id.in_(body.unit_ids))))
        if found != set(body.unit_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": {"unit_ids": "unknown_unit"}})
    return {"grades": sorted(set(body.grades)), "unit_ids": sorted(set(body.unit_ids))}


@router.post("/waves/preview")
def preview_wave(body: WaveBody, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    return onboarding.wave_candidates(db, _criteria(db, body))


@router.post("/waves", status_code=status.HTTP_201_CREATED)
def create_wave(body: WaveBody, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    wave = OnboardingWave(
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        criteria=_criteria(db, body),
        starts_on=body.starts_on,
        created_by=principal.user.id,
    )
    db.add(wave)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.wave.created",
        resource_type="onboarding_wave",
        resource_id=wave.id,
        request_id=principal.request_id,
        metadata=wave.criteria,
    )
    db.commit()
    return onboarding.wave_ref(wave)


@router.post("/waves/{wave_id}/launch")
def launch_wave(wave_id: str, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)):
    """Issue activation codes and return them once, as CSV, for distribution through HR's usual channel."""
    wave = db.get(OnboardingWave, wave_id)
    if wave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wave not found")
    issued = onboarding.launch_wave(db, wave, principal.user.id)
    if not issued:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "nobody_to_invite", "message": "Everyone in this wave has already activated"},
        )
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.wave.launched",
        resource_type="onboarding_wave",
        resource_id=wave.id,
        request_id=principal.request_id,
        metadata={"codes_issued": len(issued)},
    )
    db.commit()
    return Response(
        onboarding.codes_csv(issued),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="activation-codes-{wave.id}.csv"',
            "X-Codes-Issued": str(len(issued)),
        },
    )


class ReminderBody(BaseModel):
    message: str = Field(min_length=10, max_length=1500)
    message_ar: str | None = Field(default=None, max_length=1500)


@router.post("/waves/{wave_id}/reminder")
def send_reminder(
    wave_id: str, body: ReminderBody, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)
):
    """Post a reminder that people who have not finished see on their welcome page."""
    wave = db.get(OnboardingWave, wave_id)
    if wave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wave not found")
    wave.reminder_message, wave.reminder_message_ar = body.message.strip(), (body.message_ar or "").strip() or None
    now = utcnow()
    count = 0
    for p in db.scalars(
        select(OnboardingProgress).where(
            OnboardingProgress.wave_id == wave.id, OnboardingProgress.completed_at.is_(None)
        )
    ):
        p.reminders_sent += 1
        p.last_reminded_at = now
        count += 1
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.wave.reminder",
        resource_type="onboarding_wave",
        resource_id=wave.id,
        request_id=principal.request_id,
        metadata={"recipients": count},
    )
    db.commit()
    return {"recipients": count, "wave": onboarding.wave_ref(wave)}


class AiBody(BaseModel):
    language: Lang = "en"
    refresh: bool = False


def _ai(db: Session, principal: Principal, task: str, payload: dict, body: AiBody, **subject) -> dict:
    try:
        return ai.generate(
            db,
            task,
            payload,
            language=body.language,
            actor_id=principal.user.id,
            refresh=body.refresh,
            request_id=principal.request_id,
            **subject,
        )
    except ai.AIError as exc:
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if exc.code == "rate_limited"
            else (
                status.HTTP_409_CONFLICT
                if exc.code in ("disabled", "feature_disabled", "not_configured")
                else status.HTTP_502_BAD_GATEWAY
            )
        )
        raise HTTPException(code, {"code": exc.code, "message": exc.message}) from exc


@router.post("/waves/{wave_id}/reminder-draft")
def reminder_draft(
    wave_id: str, body: AiBody, principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)
):
    wave = db.get(OnboardingWave, wave_id)
    if wave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wave not found")
    payload = {
        "wave": wave.name,
        "launched_days_ago": (utcnow() - wave.launched_at).days if wave.launched_at else None,
        "people_in_wave": wave.employee_count,
        **onboarding.wave_funnel(db, wave.id),
        "journey_steps": [
            "activate account with code",
            "choose language",
            "guided tour",
            "acknowledge workplace policies",
            "3-question policy check",
        ],
    }
    return _ai(db, principal, "onboarding_reminder", payload, body, subject_type="onboarding_wave", subject_id=wave.id)


# -------------------------------------------------------------------- journey
def _employee(db: Session, principal: Principal) -> EmployeeProfile | None:
    return db.get(EmployeeProfile, principal.employee_id) if principal.employee_id else None


def _journey(db: Session, principal: Principal) -> dict:
    user = principal.user
    progress = onboarding.progress_for(db, user)
    employee = _employee(db, principal)
    required = onboarding.required_policies(db, employee)
    acked = onboarding.acknowledged(db, user.id)
    wave = db.get(OnboardingWave, progress.wave_id) if progress.wave_id else None
    reminder = None
    if wave and wave.reminder_message and not progress.completed_at:
        reminder = {"message": wave.reminder_message, "message_ar": wave.reminder_message_ar}
    unit = db.get(OrgUnit, employee.org_unit_id) if employee else None
    return {
        "steps": [
            {"key": "activated", "done_at": _iso(progress.activated_at)},
            {"key": "language", "done_at": _iso(progress.language_set_at)},
            {"key": "tour", "done_at": _iso(progress.tour_done_at)},
            {"key": "policies", "done_at": _iso(progress.policies_ack_at)},
            {"key": "quiz", "done_at": _iso(progress.quiz_passed_at)},
        ],
        "completed_at": _iso(progress.completed_at),
        "quiz_score": progress.quiz_score,
        "quiz_attempts": progress.quiz_attempts,
        "locale": user.locale,
        "wave": {"id": wave.id, "name": wave.name} if wave else None,
        "reminder": reminder,
        "profile": {
            "grade": employee.grade if employee else None,
            "job_title": employee.role_title if employee else None,
            "unit": {"name": unit.name, "name_ar": unit.name_ar, "type": unit.unit_type} if unit else None,
            "roles": sorted({g.role_code for g in principal.grants}),
        },
        "policies": [
            {
                "id": p.id,
                "code": p.policy_code,
                "version": p.version,
                "title": p.title,
                "title_ar": p.title_ar,
                "summary": p.summary,
                "summary_ar": p.summary_ar,
                "acknowledged": p.id in acked,
            }
            for p in required
        ],
    }


@router.get("/me")
def my_journey(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    data = _journey(db, principal)
    db.commit()
    return data


class LanguageBody(BaseModel):
    locale: Lang


@router.post("/me/language")
def set_language(body: LanguageBody, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    progress = onboarding.progress_for(db, principal.user)
    principal.user.locale = body.locale
    progress.language_set_at = progress.language_set_at or utcnow()
    onboarding.refresh_completion(progress)
    db.commit()
    return _journey(db, principal)


@router.post("/me/tour")
def tour_done(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    progress = onboarding.progress_for(db, principal.user)
    progress.tour_done_at = progress.tour_done_at or utcnow()
    onboarding.refresh_completion(progress)
    db.commit()
    return _journey(db, principal)


class AckBody(BaseModel):
    policy_version_ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/me/acknowledge")
def acknowledge(body: AckBody, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    progress = onboarding.progress_for(db, principal.user)
    required = {p.id for p in onboarding.required_policies(db, _employee(db, principal))}
    unknown = set(body.policy_version_ids) - required
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": {"policy_version_ids": "not_required"}})
    acked = onboarding.acknowledged(db, principal.user.id)
    for pid in set(body.policy_version_ids) - acked:
        db.add(PolicyAcknowledgement(user_id=principal.user.id, policy_version_id=pid))
    if required <= acked | set(body.policy_version_ids):
        progress.policies_ack_at = progress.policies_ack_at or utcnow()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="onboarding.policies.acknowledged",
        resource_type="user",
        resource_id=principal.user.id,
        request_id=principal.request_id,
        metadata={"policies": len(body.policy_version_ids)},
    )
    onboarding.refresh_completion(progress)
    db.commit()
    return _journey(db, principal)


def _quiz_payload(db: Session, principal: Principal) -> dict:
    policies = onboarding.required_policies(db, None)  # the quiz covers the workplace policies everyone shares
    return {
        "policies": [
            {"code": p.policy_code, "version": p.version, "title": p.title, "requirement": p.summary} for p in policies
        ],
        "break_allowance_minutes": settings_store.get(db, "workplace.break_allowance_minutes"),
    }


@router.get("/me/quiz")
def get_quiz(language: Lang = "en", principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Three questions. Written by the AI assistant when it is available, otherwise the built-in set."""
    try:
        result = ai.generate(
            db,
            "policy_quiz",
            _quiz_payload(db, principal),
            language=language,
            actor_id=principal.user.id,
            subject_type="onboarding_quiz",
            request_id=principal.request_id,
        )
        if onboarding.valid_quiz(result["output"]):
            return {
                "quiz_id": result["meta"]["id"],
                "source": "ai",
                "model": result["meta"]["model"],
                "questions": onboarding.public_quiz(result["output"]),
            }
    except ai.AIError:
        pass
    allowance = settings_store.get(db, "workplace.break_allowance_minutes")
    quiz = onboarding.static_quiz(allowance, language)
    return {
        "quiz_id": f"static-{language}",
        "source": "built_in",
        "model": None,
        "questions": onboarding.public_quiz(quiz),
    }


class QuizAnswers(BaseModel):
    quiz_id: str = Field(max_length=40)
    answers: list[int] = Field(min_length=3, max_length=3)


@router.post("/me/quiz")
def submit_quiz(body: QuizAnswers, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if body.quiz_id.startswith("static-"):
        language = body.quiz_id.removeprefix("static-")
        quiz = onboarding.static_quiz(
            settings_store.get(db, "workplace.break_allowance_minutes"), language if language in ("en", "ar") else "en"
        )
    else:
        record = db.get(AIGeneration, body.quiz_id)
        if record is None or record.task != "policy_quiz" or not onboarding.valid_quiz(record.output):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
        quiz = record.output
    questions = quiz["questions"]
    score = sum(1 for q, a in zip(questions, body.answers, strict=True) if q["answer_index"] == a)
    progress = onboarding.progress_for(db, principal.user)
    progress.quiz_attempts += 1
    progress.quiz_score = max(progress.quiz_score or 0, score)
    passed = score >= onboarding.QUIZ_PASS
    if passed:
        progress.quiz_passed_at = progress.quiz_passed_at or utcnow()
    onboarding.refresh_completion(progress)
    db.commit()
    return {
        "score": score,
        "out_of": len(questions),
        "passed": passed,
        "review": [
            {"correct_index": q["answer_index"], "your_index": a, "explanation": q.get("explanation")}
            for q, a in zip(questions, body.answers, strict=True)
        ],
        "journey": _journey(db, principal),
    }


@router.post("/me/welcome")
def welcome(body: AiBody, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """A role-specific welcome written by the AI assistant (pseudonymised: role and unit type only)."""
    employee = _employee(db, principal)
    unit = db.get(OrgUnit, employee.org_unit_id) if employee else None
    payload = {
        "roles": sorted({g.role_code for g in principal.grants}),
        "job_title": employee.role_title if employee else None,
        "unit_type": unit.unit_type if unit else None,
        "customer_facing": employee.customer_facing if employee else None,
        "platform_features": [
            "own findings with evidence, acknowledge or explain",
            "learning and coaching plan",
            "attendance, breaks and dress-code record with the option to explain an exception",
            "policies and control rules register",
        ],
    }
    return _ai(db, principal, "onboarding_welcome", payload, body, subject_type="onboarding_welcome")
