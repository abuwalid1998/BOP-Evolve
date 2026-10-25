"""Pipeline and model health."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dashboard import pipeline_overview
from app.api.deps import Principal, require
from app.db import get_db, utcnow
from app.models import IngestionRun, ModelRegistry, ModelRun, Pipeline, QuarantinedRecord, SourceSystem
from app.services import audit

router = APIRouter(prefix="/api", tags=["operations"])


def _iso(v):
    return v.isoformat() if v else None


def pipeline_dict(db: Session, p: Pipeline) -> dict:
    source = db.get(SourceSystem, p.source_system_id)
    last_run = db.scalar(
        select(IngestionRun).where(IngestionRun.pipeline_id == p.id).order_by(IngestionRun.started_at.desc()).limit(1)
    )
    now = utcnow()
    freshness_minutes = (now - p.last_success_at).total_seconds() / 60 if p.last_success_at else None
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "source": {
            "code": source.code,
            "name": source.name,
            "approved": source.approved_for_use,
            "enabled": source.enabled,
        },
        "state": p.state,
        "state_changed_at": _iso(p.state_changed_at),
        "last_run_at": _iso(p.last_run_at),
        "last_success_at": _iso(p.last_success_at),
        "next_run_at": _iso(p.next_run_at),
        "schedule_seconds": p.schedule_seconds,
        "freshness_sla_minutes": p.freshness_sla_minutes,
        "freshness_minutes": round(freshness_minutes, 1) if freshness_minutes is not None else None,
        "sla_breached": freshness_minutes is not None and freshness_minutes > p.freshness_sla_minutes,
        "queue_lag_seconds": p.queue_lag_seconds,
        "last_error": p.last_error,
        "last_request_id": p.last_request_id,
        "owner": p.owner,
        "runbook_url": p.runbook_url,
        "last_run": (
            {
                "id": last_run.id,
                "status": last_run.status,
                "records_read": last_run.records_read,
                "records_written": last_run.records_written,
                "records_rejected": last_run.records_rejected,
                "records_duplicated": last_run.records_duplicated,
                "duration_ms": last_run.duration_ms,
                "request_id": last_run.request_id,
            }
            if last_run
            else None
        ),
    }


@router.get("/pipelines/status")
def pipelines_status(principal: Principal = Depends(require("ops.view")), db: Session = Depends(get_db)):
    pipelines = db.scalars(select(Pipeline).order_by(Pipeline.code)).all()
    return {
        "generated_at": utcnow().isoformat(),
        "synthetic": True,
        "overview": pipeline_overview(db),
        "pipelines": [pipeline_dict(db, p) for p in pipelines],
    }


@router.get("/pipelines/{pipeline_id}/runs")
def pipeline_runs(
    pipeline_id: str,
    limit: int = Query(30, ge=1, le=200),
    principal: Principal = Depends(require("ops.view")),
    db: Session = Depends(get_db),
):
    if db.get(Pipeline, pipeline_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    runs = db.scalars(
        select(IngestionRun)
        .where(IngestionRun.pipeline_id == pipeline_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
    ).all()
    quarantine = db.scalars(
        select(QuarantinedRecord)
        .join(IngestionRun, IngestionRun.id == QuarantinedRecord.ingestion_run_id)
        .where(IngestionRun.pipeline_id == pipeline_id)
        .order_by(QuarantinedRecord.created_at.desc())
        .limit(20)
    ).all()
    return {
        "runs": [
            {
                "id": r.id,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "status": r.status,
                "records_read": r.records_read,
                "records_written": r.records_written,
                "records_rejected": r.records_rejected,
                "records_duplicated": r.records_duplicated,
                "duration_ms": r.duration_ms,
                "request_id": r.request_id,
                "error_summary": r.error_summary,
            }
            for r in runs
        ],
        "quarantine": [
            {
                "id": q.id,
                "run_id": q.ingestion_run_id,
                "source_record_key": q.source_record_key,
                "reason": q.reason,
                "created_at": _iso(q.created_at),
            }
            for q in quarantine
        ],
    }


@router.post("/pipelines/{pipeline_id}/{action}")
def control_pipeline(
    pipeline_id: str,
    action: str,
    principal: Principal = Depends(require("ops.manage")),
    db: Session = Depends(get_db),
):
    if action not in ("pause", "resume"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown action")
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    source = db.get(SourceSystem, pipeline.source_system_id)
    if action == "resume" and not source.approved_for_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "Source is not approved for use; it cannot be resumed")
    previous = pipeline.state
    now = utcnow()
    if action == "pause":
        pipeline.state = "PAUSED"
        pipeline.last_error = "Paused by operator"
    else:
        pipeline.state = "HEALTHY"
        pipeline.last_error = None
        pipeline.next_run_at = now + timedelta(seconds=5)
    pipeline.state_changed_at = now
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action=f"pipeline.{action}",
        resource_type="pipeline",
        resource_id=pipeline.id,
        request_id=principal.request_id,
        metadata={"from": previous, "to": pipeline.state},
    )
    db.commit()
    return pipeline_dict(db, pipeline)


@router.get("/models/status")
def models_status(principal: Principal = Depends(require("ops.view")), db: Session = Depends(get_db)):
    models = db.scalars(select(ModelRegistry).order_by(ModelRegistry.name)).all()
    since = utcnow() - timedelta(days=30)
    result = []
    for m in models:
        runs = db.scalars(select(ModelRun).where(ModelRun.model_id == m.id, ModelRun.run_at >= since)).all()
        reviewed = [r for r in runs if r.review_status != "pending"]
        overridden = [r for r in reviewed if r.review_status == "overridden"]
        result.append(
            {
                "id": m.id,
                "name": m.name,
                "version": m.version,
                "purpose": m.purpose,
                "status": m.status,
                "status_is_simulated": True,
                "state_changed_at": _iso(m.state_changed_at),
                "owner": m.owner,
                "approved_at": _iso(m.approved_at),
                "last_validation_at": _iso(m.last_validation_at),
                "last_run_at": _iso(m.last_run_at),
                "latency_ms_p50": m.latency_ms_p50,
                "missing_input_rate": m.missing_input_rate,
                "drift_score": m.drift_score,
                "override_rate": round(len(overridden) / len(reviewed), 3) if reviewed else m.override_rate,
                "runs_30d": len(runs),
                "limitations": m.limitations,
            }
        )
    return {"generated_at": utcnow().isoformat(), "models": result}
