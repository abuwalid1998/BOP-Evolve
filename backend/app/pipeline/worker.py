"""Simulated ingestion worker.

Generates a synthetic event stream so the dashboard behaves "live": each
pipeline runs on its schedule, validates and de-duplicates records,
quarantines malformed ones, applies the versioned rules to create
*potential* findings for human review, and updates pipeline / model health.

Never point this worker at production systems.
"""

import hashlib
import logging
import random
import signal
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, new_id, utcnow
from app.models import (
    EmployeeProfile,
    EvidenceRef,
    Finding,
    IngestionRun,
    MistakeRule,
    ModelRegistry,
    ModelRun,
    OrgUnit,
    Pipeline,
    PolicyVersion,
    QuarantinedRecord,
    ServiceCase,
    ServiceHeartbeat,
    SourceSystem,
)
from app.pipeline.catalogue import CASE_TYPES, INTERACTION_TYPES, explanation

log = logging.getLogger("bop_evolve.worker")
CASE_PIPELINES = {"qa-reviews", "crm-cases", "complaints", "call-metadata"}
_running = True


def _stop(*_):
    global _running
    _running = False


def _outcome(profile: str, rng: random.Random) -> str:
    roll = rng.random()
    if profile == "failing":
        return "failed" if roll < 0.7 else "partial"
    if profile == "flaky":
        return "failed" if roll < 0.08 else "partial" if roll < 0.4 else "succeeded"
    return "failed" if roll < 0.01 else "succeeded"


def _ingest_cases(db: Session, pipeline: Pipeline, run: IngestionRun, rng: random.Random) -> tuple[int, int, int, int]:
    employees = db.execute(
        select(EmployeeProfile.id, EmployeeProfile.org_unit_id, EmployeeProfile.pseudonym, OrgUnit.code)
        .join(OrgUnit, OrgUnit.id == EmployeeProfile.org_unit_id)
        .where(EmployeeProfile.status == "active")
    ).all()
    if not employees:
        return 0, 0, 0, 0
    rules = {r.category: r for r in db.scalars(select(MistakeRule).where(MistakeRule.active.is_(True)))}
    rules_engine = db.scalar(select(ModelRegistry).where(ModelRegistry.name == "Procedure deviation rules engine"))
    now = utcnow()
    read = rng.randint(2, 8)
    written = rejected = duplicated = 0
    for _ in range(read):
        emp_id, unit_id, pseudonym, unit_code = rng.choice(employees)
        if rng.random() < (0.12 if pipeline.demo_profile != "stable" else 0.03):
            db.add(
                QuarantinedRecord(
                    ingestion_run_id=run.id,
                    source_record_key=f"SRC-{rng.randint(10000, 99999)}",
                    reason=rng.choice(
                        ["missing_required_field:employee_ref", "schema_mismatch:occurred_at", "unknown_case_type"]
                    ),
                    payload_redacted={"fields_present": ["case_type"]},
                )
            )
            rejected += 1
            continue
        key = f"LIVE-{pseudonym}-{int(now.timestamp())}-{rng.randint(0, 999):03d}"
        if rng.random() < 0.06:
            duplicated += 1  # same source key seen before: deduplicated, not re-written
            continue
        case_type = rng.choice(list(CASE_TYPES))
        if unit_code.startswith("CC-") and case_type in ("cash_transaction", "account_opening"):
            case_type = "general_inquiry"
        rule = rules.get(case_type)
        policy = db.get(PolicyVersion, rule.policy_version_id) if rule else None
        case = ServiceCase(
            id=new_id("CS"),
            source_system_id=pipeline.source_system_id,
            source_case_key=key,
            employee_id=emp_id,
            org_unit_id=unit_id,
            case_type=case_type,
            ingestion_run_id=run.id,
            interaction_type="phone"
            if unit_code == "CC-VOICE"
            else "chat"
            if unit_code == "CC-CHAT"
            else rng.choice(INTERACTION_TYPES),
            occurred_at=now - timedelta(minutes=rng.randint(1, 50)),
            complexity_band=rng.choice(("low", "medium", "high")),
            policy_version_id=policy.id if policy else None,
        )
        db.add(case)
        db.flush()  # evidence and model runs reference the case but have no ORM relationship to order them
        written += 1
        if rule and rng.random() < 0.09:
            spec = CASE_TYPES[case_type]
            confidence = round(rng.uniform(0.6, 0.96), 2)
            db.add(
                Finding(
                    id=new_id("FND"),
                    case_id=case.id,
                    rule_id=rule.id,
                    status="POTENTIAL",
                    severity=rule.severity,
                    reason_code=spec["rule"],
                    observed_action=spec["observed"][0],
                    observed_action_ar=spec["observed"][1],
                    explanation=explanation(case_type, policy.version, "en"),
                    explanation_ar=explanation(case_type, policy.version, "ar"),
                    detection_method="rule",
                    model_id=rules_engine.id if rules_engine else None,
                    confidence=confidence,
                )
            )
            db.flush()
            ref = f"qa_review_form://{key}"
            db.add(
                EvidenceRef(
                    case_id=case.id,
                    evidence_type="qa_review_form",
                    secure_reference=ref,
                    content_hash=hashlib.sha256(ref.encode()).hexdigest(),
                    access_class="internal",
                    summary="Synthetic evidence pointer — content stays in the source system.",
                )
            )
            if rules_engine:
                db.add(
                    ModelRun(
                        model_id=rules_engine.id,
                        case_id=case.id,
                        output_summary=f"potential:{spec['rule']}",
                        confidence=confidence,
                        latency_ms=rng.randint(15, 90),
                    )
                )
    return read, written, rejected, duplicated


def run_pipeline(db: Session, pipeline: Pipeline, rng: random.Random) -> None:
    now = utcnow()
    source = db.get(SourceSystem, pipeline.source_system_id)
    if not source.enabled or not source.approved_for_use:
        pipeline.state, pipeline.last_error = "PAUSED", "Source disabled or not approved"
        pipeline.next_run_at = now + timedelta(seconds=pipeline.schedule_seconds)
        return
    request_id = new_id("REQ")
    run = IngestionRun(
        id=new_id("RUN"),
        pipeline_id=pipeline.id,
        source_system_id=pipeline.source_system_id,
        status="running",
        request_id=request_id,
        started_at=now,
    )
    db.add(run)
    pipeline.state, pipeline.state_changed_at, pipeline.last_run_at = "RUNNING", now, now
    db.flush()

    outcome = _outcome(pipeline.demo_profile, rng)
    if outcome == "failed":
        run.status, run.error_summary = "failed", "Upstream API returned 503 (simulated)"
        pipeline.state, pipeline.last_error = "FAILED", run.error_summary
    else:
        if pipeline.code in CASE_PIPELINES:
            read, written, rejected, duplicated = _ingest_cases(db, pipeline, run, rng)
        else:
            read = rng.randint(5, 40)
            rejected = rng.randint(0, 2)
            duplicated = rng.randint(0, 2)
            written = read - rejected - duplicated
        run.records_read, run.records_written = read, written
        run.records_rejected, run.records_duplicated = rejected, duplicated
        degraded = outcome == "partial" or (read and rejected / read > 0.1)
        run.status = "partial" if degraded else "succeeded"
        pipeline.state = "DEGRADED" if degraded else "HEALTHY"
        pipeline.last_error = "Rejected-record rate above 10% (simulated)" if degraded else None
        pipeline.last_success_at = now
    pipeline.queue_lag_seconds = rng.randint(200, 600) if pipeline.state == "DEGRADED" else rng.randint(0, 30)
    finished = utcnow()
    run.finished_at = finished
    run.duration_ms = int((finished - now).total_seconds() * 1000) + rng.randint(300, 4000)
    pipeline.state_changed_at = finished
    pipeline.last_request_id = request_id
    pipeline.next_run_at = finished + timedelta(seconds=pipeline.schedule_seconds)


def tick(db: Session, rng: random.Random) -> None:
    now = utcnow()
    for pipeline in db.scalars(select(Pipeline)):
        if pipeline.state == "PAUSED":
            continue
        if pipeline.next_run_at is None or pipeline.next_run_at <= now:
            run_pipeline(db, pipeline, rng)
        elif (
            pipeline.state not in ("RUNNING", "FAILED", "STALE")
            and pipeline.last_success_at
            and now - pipeline.last_success_at > timedelta(minutes=pipeline.freshness_sla_minutes)
        ):
            pipeline.state, pipeline.state_changed_at = "STALE", now
            pipeline.last_error = "No successful sync within freshness SLA"

    for model in db.scalars(
        select(ModelRegistry).where(ModelRegistry.status.in_(("DEPLOYED", "MONITORING", "DEGRADED")))
    ):
        model.last_run_at = now
        if model.latency_ms_p50:
            model.latency_ms_p50 = round(max(10.0, model.latency_ms_p50 * rng.uniform(0.95, 1.05)), 1)
        if model.drift_score is not None:
            model.drift_score = round(min(0.6, max(0.0, model.drift_score + rng.uniform(-0.01, 0.01))), 3)

    beat = db.get(ServiceHeartbeat, "pipeline-worker") or ServiceHeartbeat(name="pipeline-worker")
    beat.last_beat_at, beat.detail = now, {"status": "running"}
    db.merge(beat)
    db.commit()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    rng = random.Random()
    log.info("Simulated pipeline worker started (tick=%ss). Demo data only.", settings.worker_tick_seconds)
    while _running:
        try:
            with SessionLocal() as db:
                tick(db, rng)
        except Exception:  # noqa: BLE001 - keep the simulated stream alive and visible in logs
            log.exception("Worker tick failed")
        for _ in range(settings.worker_tick_seconds * 10):
            if not _running:
                break
            time.sleep(0.1)
    log.info("Worker stopped")


if __name__ == "__main__":
    main()
