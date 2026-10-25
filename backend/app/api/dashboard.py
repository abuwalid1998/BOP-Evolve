from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import (
    EmployeeProfile,
    EmployeeResponse,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    LearningGeneration,
    ModelRegistry,
    Pipeline,
    ServiceCase,
    ServiceHeartbeat,
)
from app.services.scoping import case_condition, employee_condition

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

WORKER_STALE_SECONDS = 90


def pipeline_overview(db: Session) -> dict:
    pipelines = list(db.scalars(select(Pipeline)))
    states = Counter(p.state for p in pipelines)
    last_success = max((p.last_success_at for p in pipelines if p.last_success_at), default=None)
    heartbeat = db.get(ServiceHeartbeat, "pipeline-worker")
    now = utcnow()
    worker_ok = heartbeat is not None and (now - heartbeat.last_beat_at).total_seconds() < WORKER_STALE_SECONDS
    return {
        "states": dict(states),
        "total": len(pipelines),
        "last_successful_ingestion_at": last_success.isoformat() if last_success else None,
        "worker": {
            "alive": worker_ok,
            "last_beat_at": heartbeat.last_beat_at.isoformat() if heartbeat else None,
        },
        "alerts": [
            {"pipeline": p.code, "name": p.name, "state": p.state, "error": p.last_error}
            for p in pipelines
            if p.state in ("FAILED", "STALE", "DEGRADED")
        ],
    }


@router.get("/summary")
def summary(
    days: int = Query(90, ge=7, le=365),
    principal: Principal = Depends(require("dashboard.view")),
    db: Session = Depends(get_db),
):
    scope = principal.scope(db, "dashboard.view")
    cond = case_condition(scope)
    now = utcnow()
    since = now - timedelta(days=days)

    case_count = db.scalar(select(func.count()).select_from(ServiceCase).where(cond, ServiceCase.occurred_at >= since))
    status_rows = db.execute(
        select(Finding.status, func.count())
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond, ServiceCase.occurred_at >= since)
        .group_by(Finding.status)
    ).all()
    statuses = {s: c for s, c in status_rows}

    awareness_rows = db.execute(
        select(EmployeeResponse.awareness_state, func.count())
        .join(Finding, Finding.id == EmployeeResponse.finding_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond, ServiceCase.occurred_at >= since, EmployeeResponse.stage == "before_feedback")
        .group_by(EmployeeResponse.awareness_state)
    ).all()

    actions = db.execute(
        select(ImprovementAction.status, ImprovementAction.due_at, ImprovementAction.completed_at)
        .join(Finding, Finding.id == ImprovementAction.finding_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond, ServiceCase.occurred_at >= since, ImprovementAction.status != "cancelled")
    ).all()
    due = [a for a in actions if a.due_at <= now or a.completed_at]
    completed = [a for a in due if a.completed_at]
    overdue = [a for a in actions if a.due_at < now and not a.completed_at]

    follow = db.execute(
        select(FollowUpEvaluation.recurred, func.count())
        .join(Finding, Finding.id == FollowUpEvaluation.finding_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond)
        .group_by(FollowUpEvaluation.recurred)
    ).all()
    follow_counts = {bool(r): c for r, c in follow}
    follow_total = sum(follow_counts.values())

    # Current approved generation per employee in scope.
    latest = (
        select(LearningGeneration.employee_id, func.max(LearningGeneration.version).label("v"))
        .where(LearningGeneration.status == "approved")
        .group_by(LearningGeneration.employee_id)
        .subquery()
    )
    gen_rows = db.execute(
        select(LearningGeneration.generation_code, func.count())
        .join(
            latest,
            (latest.c.employee_id == LearningGeneration.employee_id) & (latest.c.v == LearningGeneration.version),
        )
        .join(EmployeeProfile, EmployeeProfile.id == LearningGeneration.employee_id)
        .where(employee_condition(scope))
        .group_by(LearningGeneration.generation_code)
    ).all()
    pending_generations = db.scalar(
        select(func.count())
        .select_from(LearningGeneration)
        .join(EmployeeProfile, EmployeeProfile.id == LearningGeneration.employee_id)
        .where(employee_condition(scope), LearningGeneration.status == "proposed")
    )

    # Weekly trend: findings (excluding dismissed) per 100 cases.
    weeks = min(days // 7, 26)
    trend_since = now - timedelta(weeks=weeks)
    case_times = db.scalars(select(ServiceCase.occurred_at).where(cond, ServiceCase.occurred_at >= trend_since)).all()
    finding_times = db.execute(
        select(ServiceCase.occurred_at, Finding.status)
        .join(Finding, Finding.case_id == ServiceCase.id)
        .where(cond, ServiceCase.occurred_at >= trend_since)
    ).all()
    buckets = []
    for i in range(weeks):
        start = trend_since + timedelta(weeks=i)
        end = start + timedelta(weeks=1)
        n_cases = sum(1 for t in case_times if start <= t < end)
        n_conf = sum(1 for t, s in finding_times if start <= t < end and s in ("CONFIRMED", "AMENDED"))
        n_pot = sum(1 for t, s in finding_times if start <= t < end and s in ("POTENTIAL", "DISPUTED"))
        buckets.append(
            {
                "week_start": start.date().isoformat(),
                "cases": n_cases,
                "confirmed": n_conf,
                "pending": n_pot,
                "rate_per_100": round(100 * n_conf / n_cases, 2) if n_cases else None,
                "pending_per_100": round(100 * n_pot / n_cases, 2) if n_cases else None,
            }
        )

    models = Counter(db.scalars(select(ModelRegistry.status)))
    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "synthetic": True,
        "totals": {
            "reviewed_interactions": case_count,
            "potential_findings": sum(statuses.values()),
            "by_status": statuses,
        },
        "recurrence": {
            "evaluated": follow_total,
            "recurred": follow_counts.get(True, 0),
            "rate": round(follow_counts.get(True, 0) / follow_total, 4) if follow_total else None,
        },
        "awareness": {k: v for k, v in awareness_rows if k},
        "actions": {
            "due_or_completed": len(due),
            "completed": len(completed),
            "overdue": len(overdue),
            "completion_rate": round(len(completed) / len(due), 4) if due else None,
        },
        "generations": {"distribution": dict(gen_rows), "pending_approval": pending_generations},
        "trend": buckets,
        "pipelines": pipeline_overview(db),
        "models": dict(models),
    }
