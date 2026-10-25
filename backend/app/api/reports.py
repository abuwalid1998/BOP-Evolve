"""Tabular reports with optional CSV export."""

import csv
import io
from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.db import get_db, utcnow
from app.models import (
    CoachingSession,
    EmployeeProfile,
    EmployeeResponse,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    IngestionRun,
    MistakeRule,
    ModelRegistry,
    ModelRun,
    OrgUnit,
    Pipeline,
    ServiceCase,
    TrainingRecord,
    User,
)
from app.services import audit
from app.services.scoping import case_condition

router = APIRouter(prefix="/api/reports", tags=["reports"])

REPORTS = {
    "quality-trends": ("reports.view", "Branch / region quality trends"),
    "common-issues": ("reports.view", "Common process and policy issues"),
    "repeat-after-coaching": ("reports.view", "Repeat findings after coaching"),
    "training-effectiveness": ("reports.view", "Training effectiveness"),
    "awaiting-response": ("reports.view", "Cases awaiting employee response or reviewer decision"),
    "overdue-actions": ("reports.view", "Corrective-action overdue report"),
    "data-quality": ("reports.ops", "Data quality and pipeline health"),
    "model-performance": ("reports.ops", "Model performance, drift and override rates"),
}


@router.get("")
def catalogue(principal: Principal = Depends(get_principal)):
    return [
        {"code": code, "title": title, "permission": perm}
        for code, (perm, title) in REPORTS.items()
        if principal.has(perm)
    ]


def _quality_trends(db, cond, since):
    rows = db.execute(
        select(ServiceCase.id, ServiceCase.occurred_at, ServiceCase.org_unit_id, Finding.status)
        .outerjoin(Finding, Finding.case_id == ServiceCase.id)
        .where(cond, ServiceCase.occurred_at >= since)
    ).all()
    units = {u.id: u for u in db.scalars(select(OrgUnit))}

    def region_of(uid):
        u = units.get(uid)
        while u is not None and u.unit_type not in ("region", "department"):
            u = units.get(u.parent_id) if u.parent_id else None
        return u

    agg: dict[tuple, list] = defaultdict(lambda: [set(), 0, 0])
    for case_id, occurred, unit_id, st in rows:
        region = region_of(unit_id)
        key = (occurred.strftime("%Y-%m"), region.code if region else "-", region.name if region else "-")
        agg[key][0].add(case_id)
        if st in ("CONFIRMED", "AMENDED"):
            agg[key][1] += 1
        elif st == "DISMISSED":
            agg[key][2] += 1
    columns = ["month", "unit_code", "unit_name", "cases", "confirmed", "dismissed", "confirmed_per_100"]
    out = []
    for (month, code, name), (case_ids, conf, dis) in sorted(agg.items()):
        n = len(case_ids)
        out.append([month, code, name, n, conf, dis, round(100 * conf / n, 2) if n else None])
    return columns, out


def _common_issues(db, cond, since):
    rows = db.execute(
        select(MistakeRule.rule_code, MistakeRule.category, Finding.contributing_factor, func.count())
        .join(Finding, Finding.rule_id == MistakeRule.id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond, ServiceCase.occurred_at >= since, Finding.status.in_(("CONFIRMED", "AMENDED")))
        .group_by(MistakeRule.rule_code, MistakeRule.category, Finding.contributing_factor)
    ).all()
    agg: dict[tuple, Counter] = defaultdict(Counter)
    for code, cat, factor, n in rows:
        agg[(code, cat)][factor] += n
    columns = [
        "rule_code",
        "category",
        "confirmed",
        "individual_action",
        "policy_ambiguity",
        "process_design",
        "system_issue",
        "workload",
        "systemic_share",
    ]
    out = []
    for (code, cat), c in sorted(agg.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(c.values())
        systemic = c["policy_ambiguity"] + c["process_design"] + c["system_issue"]
        out.append(
            [
                code,
                cat,
                total,
                c["individual_action"],
                c["policy_ambiguity"],
                c["process_design"],
                c["system_issue"],
                c["workload"],
                round(systemic / total, 3) if total else None,
            ]
        )
    return columns, out


def _repeat_after_coaching(db, cond, since):
    coached = set(
        db.scalars(select(CoachingSession.related_finding_id).where(CoachingSession.related_finding_id.is_not(None)))
    )
    rows = db.execute(
        select(
            MistakeRule.category,
            FollowUpEvaluation.finding_id,
            FollowUpEvaluation.recurred,
            FollowUpEvaluation.comparable_cases,
        )
        .join(Finding, Finding.id == FollowUpEvaluation.finding_id)
        .join(MistakeRule, MistakeRule.id == Finding.rule_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(cond)
    ).all()
    agg: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    for cat, fid, recurred, comparable in rows:
        key = (cat, "coached" if fid in coached else "not_coached")
        agg[key][0] += 1
        agg[key][1] += int(recurred)
        agg[key][2] += comparable
    columns = ["category", "group", "evaluated_findings", "recurred", "recurrence_rate", "comparable_cases"]
    return columns, [[c, g, n, r, round(r / n, 3) if n else None, cc] for (c, g), (n, r, cc) in sorted(agg.items())]


def _training_effectiveness(db, cond, since):
    rows = db.execute(
        select(TrainingRecord.course_code, TrainingRecord.score, TrainingRecord.related_finding_id)
        .join(EmployeeProfile, EmployeeProfile.id == TrainingRecord.employee_id)
        .where(TrainingRecord.status == "completed", TrainingRecord.completed_at >= since)
    ).all()
    allowed_findings = set(
        db.scalars(select(Finding.id).join(ServiceCase, ServiceCase.id == Finding.case_id).where(cond))
    )
    recurred = dict(db.execute(select(FollowUpEvaluation.finding_id, FollowUpEvaluation.recurred)).all())
    agg: dict[str, list] = defaultdict(lambda: [0, 0.0, 0, 0])
    for course, score, fid in rows:
        if fid not in allowed_findings:
            continue
        a = agg[course]
        a[0] += 1
        a[1] += score or 0
        if fid in recurred:
            a[2] += 1
            a[3] += int(recurred[fid])
    columns = ["course_code", "completions", "avg_knowledge_check", "followed_up", "recurrence_rate"]
    return columns, [
        [c, n, round(s / n, 1) if n else None, f, round(r / f, 3) if f else None]
        for c, (n, s, f, r) in sorted(agg.items())
    ]


def _awaiting(db, cond, since):
    responded = set(db.scalars(select(EmployeeResponse.finding_id).where(EmployeeResponse.stage == "before_feedback")))
    rows = db.execute(
        select(
            Finding.id,
            Finding.case_id,
            Finding.status,
            Finding.created_at,
            MistakeRule.rule_code,
            EmployeeProfile.pseudonym,
        )
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .join(MistakeRule, MistakeRule.id == Finding.rule_id)
        .join(EmployeeProfile, EmployeeProfile.id == ServiceCase.employee_id)
        .where(cond, Finding.status.in_(("POTENTIAL", "DISPUTED", "CONFIRMED", "AMENDED")), Finding.created_at >= since)
        .order_by(Finding.created_at)
    ).all()
    now = utcnow()
    columns = ["finding_id", "case_id", "employee", "rule_code", "status", "waiting_on", "age_days"]
    out = []
    for fid, cid, st, created, code, pseud in rows:
        if st in ("POTENTIAL", "DISPUTED"):
            waiting = "reviewer"
        elif fid not in responded:
            waiting = "employee"
        else:
            continue
        out.append([fid, cid, pseud, code, st, waiting, (now - created).days])
    return columns, out


def _overdue(db, cond, since):
    now = utcnow()
    rows = db.execute(
        select(
            ImprovementAction.id,
            ImprovementAction.action_type,
            ImprovementAction.due_at,
            ImprovementAction.status,
            User.display_name,
            Finding.id,
            EmployeeProfile.pseudonym,
        )
        .join(Finding, Finding.id == ImprovementAction.finding_id)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .join(EmployeeProfile, EmployeeProfile.id == ServiceCase.employee_id)
        .join(User, User.id == ImprovementAction.owner_id)
        .where(cond, ImprovementAction.status.in_(("planned", "in_progress")), ImprovementAction.due_at < now)
        .order_by(ImprovementAction.due_at)
    ).all()
    columns = ["action_id", "action_type", "due_at", "status", "owner", "finding_id", "employee", "days_overdue"]
    return columns, [[a, t, d.date().isoformat(), s, o, f, e, (now - d).days] for a, t, d, s, o, f, e in rows]


def _data_quality(db, cond, since):
    pipelines = {p.id: p for p in db.scalars(select(Pipeline))}
    rows = db.execute(
        select(
            IngestionRun.pipeline_id,
            func.count(),
            func.sum(IngestionRun.records_read),
            func.sum(IngestionRun.records_written),
            func.sum(IngestionRun.records_rejected),
            func.sum(IngestionRun.records_duplicated),
        )
        .where(IngestionRun.started_at >= utcnow() - timedelta(days=7))
        .group_by(IngestionRun.pipeline_id)
    ).all()
    failed = dict(
        db.execute(
            select(IngestionRun.pipeline_id, func.count())
            .where(IngestionRun.started_at >= utcnow() - timedelta(days=7), IngestionRun.status == "failed")
            .group_by(IngestionRun.pipeline_id)
        ).all()
    )
    columns = [
        "pipeline",
        "state",
        "runs_7d",
        "failed_runs",
        "read",
        "written",
        "rejected",
        "duplicated",
        "rejected_rate",
    ]
    out = []
    for pid, runs, read, written, rejected, dup in rows:
        p = pipelines[pid]
        out.append(
            [
                p.code,
                p.state,
                runs,
                failed.get(pid, 0),
                read or 0,
                written or 0,
                rejected or 0,
                dup or 0,
                round((rejected or 0) / read, 3) if read else None,
            ]
        )
    return columns, sorted(out)


def _model_performance(db, cond, since):
    columns = [
        "model",
        "version",
        "status",
        "runs",
        "accepted",
        "overridden",
        "override_rate",
        "drift_score",
        "missing_input_rate",
        "latency_ms_p50",
    ]
    out = []
    for m in db.scalars(select(ModelRegistry).order_by(ModelRegistry.name)):
        counts = dict(
            db.execute(
                select(ModelRun.review_status, func.count())
                .where(ModelRun.model_id == m.id, ModelRun.run_at >= since)
                .group_by(ModelRun.review_status)
            ).all()
        )
        reviewed = counts.get("accepted", 0) + counts.get("overridden", 0)
        out.append(
            [
                m.name,
                m.version,
                m.status,
                sum(counts.values()),
                counts.get("accepted", 0),
                counts.get("overridden", 0),
                round(counts.get("overridden", 0) / reviewed, 3) if reviewed else None,
                m.drift_score,
                m.missing_input_rate,
                m.latency_ms_p50,
            ]
        )
    return columns, out


_BUILDERS = {
    "quality-trends": _quality_trends,
    "common-issues": _common_issues,
    "repeat-after-coaching": _repeat_after_coaching,
    "training-effectiveness": _training_effectiveness,
    "awaiting-response": _awaiting,
    "overdue-actions": _overdue,
    "data-quality": _data_quality,
    "model-performance": _model_performance,
}


@router.get("/{code}")
def get_report(
    code: str,
    days: int = Query(180, ge=7, le=730),
    format: str = Query("json", pattern="^(json|csv)$"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    if code not in REPORTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report")
    permission, title = REPORTS[code]
    if not principal.has(permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this report")
    # Business reports are scoped by the caller's reporting scope; ops reports are system-wide aggregates.
    scope = principal.scope(db, "reports.view") if permission == "reports.view" else None
    cond = case_condition(scope) if scope is not None else true()
    since = utcnow() - timedelta(days=days)
    columns, rows = _BUILDERS[code](db, cond, since)

    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="report.view",
        resource_type="report",
        resource_id=code,
        request_id=principal.request_id,
        metadata={"format": format, "rows": len(rows)},
    )
    db.commit()
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["# SYNTHETIC DEMO DATA - not real bank records"])
        writer.writerow(columns)
        writer.writerows(rows)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="bop-evolve-{code}.csv"'},
        )
    return {
        "code": code,
        "title": title,
        "generated_at": utcnow().isoformat(),
        "window_days": days,
        "synthetic": True,
        "columns": columns,
        "rows": rows,
    }
