"""Rules engine, rule/policy approval workflow, backtesting and back-fill."""

import random

import pytest
from sqlalchemy import select, update

from app.models import AuditEvent, Finding, MistakeRule, Pipeline, PolicyVersion, ServiceCase
from app.pipeline import worker
from app.seed import upgrade
from app.services import rules_engine

CASH = {
    "match": "all",
    "conditions": [
        {"field": "transaction_kind", "op": "eq", "value": "withdrawal"},
        {"field": "amount_ils", "op": "gt", "value": 20000},
        {"field": "second_approval_recorded", "op": "is_false"},
    ],
}
EARLY_WARNING = {
    "match": "all",
    "conditions": [
        {"field": "queue_wait_minutes", "op": "gt", "value": 20},
        {"field": "hour_of_day", "op": "gte", "value": 15},
    ],
}


def _rule_body(db, code_or_from: dict, conditions: dict, kind: str = "breach", category: str = "cash_transaction"):
    policy = db.scalar(
        select(PolicyVersion).where(PolicyVersion.policy_code == "CASH-04", PolicyVersion.status == "active")
    )
    return {
        **code_or_from,
        "category": category,
        "policy_version_id": policy.id,
        "kind": kind,
        "name": "Test rule",
        "name_ar": "قاعدة اختبار",
        "description": "Test description",
        "description_ar": "وصف الاختبار",
        "expected_action": "Do the right thing",
        "expected_action_ar": "اتباع الإجراء الصحيح",
        "severity": "high",
        "base_confidence": 0.8,
        "conditions": conditions,
    }


def test_evaluate_and_validate():
    attrs = {"transaction_kind": "withdrawal", "amount_ils": 30000, "second_approval_recorded": False}
    matched, detail = rules_engine.evaluate(CASH, attrs)
    assert matched and all(d["passed"] for d in detail)
    assert not rules_engine.matches(CASH, {**attrs, "second_approval_recorded": True})
    assert not rules_engine.matches(CASH, {"transaction_kind": "withdrawal"})  # missing facts never match
    assert rules_engine.matches({"match": "any", "conditions": CASH["conditions"]}, {"amount_ils": 25000})

    with pytest.raises(rules_engine.RuleError) as err:
        rules_engine.validate(
            "cash_transaction",
            {
                "match": "all",
                "conditions": [
                    {"field": "nope", "op": "eq", "value": 1},
                    {"field": "ack_business_days", "op": "gt", "value": 2},  # complaints only
                    {"field": "amount_ils", "op": "is_true"},  # wrong operator for a number
                    {"field": "amount_ils", "op": "gt", "value": -5},
                    {"field": "transaction_kind", "op": "in", "value": ["withdrawal", "teleport"]},
                ],
            },
        )
    assert err.value.errors == {
        "conditions.0.field": "unknown_field",
        "conditions.1.field": "not_for_case_type",
        "conditions.2.op": "invalid_operator",
        "conditions.3.value": "out_of_range",
        "conditions.4.value": "invalid_option",
    }
    clean = rules_engine.validate(
        "cash_transaction", {"conditions": [{"field": "second_approval_recorded", "op": "is_false", "value": 7}]}
    )
    assert clean == {
        "match": "all",
        "conditions": [{"field": "second_approval_recorded", "op": "is_false", "value": None}],
    }


def test_seeded_findings_match_their_rule(db):
    rows = db.execute(
        select(Finding, ServiceCase, MistakeRule)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .join(MistakeRule, MistakeRule.id == Finding.rule_id)
        .where(Finding.matched_conditions.is_not(None))  # seeded; other tests add ad-hoc findings without facts
        .limit(400)
    ).all()
    assert rows
    for finding, case, rule in rows:
        assert rules_engine.matches(rule.conditions, case.attributes), finding.id
        assert finding.matched_conditions


def test_everyone_can_read_rules_but_only_authors_can_draft(client, login, db):
    listed = client.get("/api/rules", headers=login("employee.demo"))
    assert listed.status_code == 200
    active = [r for r in listed.json() if r["status"] == "active"]
    assert len(active) == 13 and all(r["actions"] == [] for r in active)  # 7 service + 6 workplace
    assert client.get("/api/rules/catalogue", headers=login("analyst")).status_code == 200
    body = _rule_body(db, {"rule_code": "TEST_FORBIDDEN"}, CASH)
    assert client.post("/api/rules", json=body, headers=login("analyst")).status_code == 403
    assert client.post("/api/rules", json=body, headers=login("branch.n01")).status_code == 403


def test_backtest_reports_matches_forecast_and_samples_by_scope(client, login):
    full = client.post(
        "/api/rules/backtest",
        json={"category": "cash_transaction", "conditions": CASH, "days": 180},
        headers=login("risk.compliance"),
    ).json()
    assert full["matches"] > 0 and full["matches"] == full["matched_with_finding"]
    assert full["lift"] and full["lift"] > 1
    assert [f["days"] for f in full["forecast"]] == [30, 90]
    assert full["forecast"][0]["low"] <= full["forecast"][0]["expected"] <= full["forecast"][0]["high"]
    assert full["samples"]

    # The analyst sees the same aggregates but no case references (no cases.view).
    analyst = client.post(
        "/api/rules/backtest",
        json={"category": "cash_transaction", "conditions": CASH, "days": 180},
        headers=login("analyst"),
    ).json()
    assert analyst["matches"] == full["matches"] and analyst["samples"] == []

    warning = client.post(
        "/api/rules/backtest",
        json={"category": "cash_transaction", "conditions": EARLY_WARNING, "days": 270},
        headers=login("analyst"),
    ).json()
    assert warning["lift"] and warning["lift"] > 1  # long queues late in the day precede breaches

    invalid = client.post(
        "/api/rules/backtest",
        json={"category": "cash_transaction", "conditions": {"conditions": []}},
        headers=login("analyst"),
    )
    assert invalid.status_code == 422


def test_rule_version_workflow_enforces_four_eyes(client, login, db):
    author, approver = login("risk.compliance"), login("ops.policy")
    current = db.scalar(
        select(MistakeRule).where(MistakeRule.rule_code == "CASH_DUAL_APPROVAL", MistakeRule.status == "active")
    )
    stricter = {
        **CASH,
        "conditions": [
            *CASH["conditions"][:1],
            {"field": "amount_ils", "op": "gt", "value": 10000},
            CASH["conditions"][2],
        ],
    }
    created = client.post("/api/rules", json=_rule_body(db, {"from_rule_id": current.id}, stricter), headers=author)
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["status"] == "draft" and draft["version"] == str(int(current.version) + 1)
    assert set(draft["actions"]) >= {"edit", "submit"}

    # Only one open version per rule.
    again = client.post("/api/rules", json=_rule_body(db, {"from_rule_id": current.id}, stricter), headers=author)
    assert again.status_code == 409

    impact = client.get(f"/api/rules/{draft['id']}/backtest?days=180", headers=author).json()
    assert impact["comparison"]["rule"]["id"] == current.id
    assert impact["comparison"]["only_current"] == 0  # a lower threshold flags a superset

    assert client.post(f"/api/rules/{draft['id']}/approve", json={}, headers=author).status_code == 409
    assert client.post(f"/api/rules/{draft['id']}/submit", headers=author).status_code == 200
    assert client.put(f"/api/rules/{draft['id']}", json=_rule_body(db, {}, stricter), headers=author).status_code == 409
    own = client.post(f"/api/rules/{draft['id']}/approve", json={}, headers=author)
    assert own.status_code == 403 and "Four-eyes" in own.json()["detail"]
    assert client.post(f"/api/rules/{draft['id']}/reject", json={"note": "x"}, headers=approver).status_code == 422
    returned = client.post(f"/api/rules/{draft['id']}/reject", json={"note": "Explain the threshold"}, headers=approver)
    assert returned.json()["status"] == "draft" and returned.json()["review_note"] == "Explain the threshold"

    client.post(f"/api/rules/{draft['id']}/submit", headers=author)
    approved = client.post(f"/api/rules/{draft['id']}/approve", json={"note": "Agreed"}, headers=approver)
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    db.expire_all()
    assert db.get(MistakeRule, current.id).status == "retired"
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == draft["id"])))
    assert {"rule.draft_created", "rule.submitted", "rule.returned", "rule.approved"} <= actions

    # The worker now applies the new version: a 15,000 withdrawal without second approval is flagged.
    pipeline = db.scalar(select(Pipeline).where(Pipeline.code == "qa-reviews"))
    run = worker.IngestionRun(
        pipeline_id=pipeline.id, source_system_id=pipeline.source_system_id, status="running", request_id="REQ-test"
    )
    db.add(run)
    db.flush()
    original = worker.generate_attributes
    worker.generate_attributes = lambda case_type, *a, **k: (
        {"transaction_kind": "withdrawal", "amount_ils": 15000, "second_approval_recorded": False}
        if case_type == "cash_transaction"
        else original(case_type, *a, **k)
    )
    try:
        worker._ingest_cases(db, pipeline, run, random.Random(1))
        for _ in range(30):
            worker._ingest_cases(db, pipeline, run, random.Random(_ + 2))
    finally:
        worker.generate_attributes = original
    db.flush()
    flagged = db.scalars(
        select(Finding)
        .join(ServiceCase, ServiceCase.id == Finding.case_id)
        .where(ServiceCase.ingestion_run_id == run.id, ServiceCase.case_type == "cash_transaction")
    ).all()
    assert flagged and all(f.rule_id == draft["id"] for f in flagged)
    assert {c["field"] for c in flagged[0].matched_conditions} == {
        "transaction_kind",
        "amount_ils",
        "second_approval_recorded",
    }
    db.rollback()

    retired = client.post(f"/api/rules/{draft['id']}/retire", json={"note": "Back to previous"}, headers=approver)
    assert retired.json()["status"] == "retired"
    # Restore the original active version for the other tests.
    db.execute(update(MistakeRule).where(MistakeRule.id == current.id).values(status="active", retired_at=None))
    db.commit()


def test_early_warning_rules_never_raise_findings(client, login, db):
    author, approver = login("risk.compliance"), login("ops.policy")
    body = _rule_body(db, {"rule_code": "EW_LATE_LONG_QUEUE"}, EARLY_WARNING, kind="early_warning")
    rule = client.post("/api/rules", json=body, headers=author).json()
    client.post(f"/api/rules/{rule['id']}/submit", headers=author)
    assert client.post(f"/api/rules/{rule['id']}/approve", json={}, headers=approver).json()["status"] == "active"

    pipeline = db.scalar(select(Pipeline).where(Pipeline.code == "qa-reviews"))
    run = worker.IngestionRun(
        pipeline_id=pipeline.id, source_system_id=pipeline.source_system_id, status="running", request_id="REQ-test2"
    )
    db.add(run)
    db.flush()
    for seed in range(40):
        worker._ingest_cases(db, pipeline, run, random.Random(100 + seed))
    db.flush()
    rule_ids = set(
        db.scalars(
            select(Finding.rule_id)
            .join(ServiceCase, ServiceCase.id == Finding.case_id)
            .where(ServiceCase.ingestion_run_id == run.id)
        )
    )
    assert rule["id"] not in rule_ids
    db.rollback()
    client.post(f"/api/rules/{rule['id']}/retire", json={"note": "Test finished"}, headers=approver)


def test_policy_version_workflow(client, login, db):
    author, approver = login("ops.policy"), login("risk.compliance")
    current = db.scalar(
        select(PolicyVersion).where(PolicyVersion.policy_code == "CMP-02", PolicyVersion.status == "active")
    )
    draft = client.post(
        "/api/rules/policies",
        json={
            "from_policy_id": current.id,
            "title": current.title,
            "title_ar": current.title_ar,
            "summary": "Acknowledge within one business day.",
            "summary_ar": "الإقرار بالاستلام خلال يوم عمل واحد.",
        },
        headers=author,
    )
    assert draft.status_code == 201, draft.text
    pid = draft.json()["id"]
    assert draft.json()["version"] == "1.2"
    client.post(f"/api/rules/policies/{pid}/submit", headers=author)
    assert client.post(f"/api/rules/policies/{pid}/approve", json={}, headers=author).status_code == 403
    approved = client.post(f"/api/rules/policies/{pid}/approve", json={}, headers=approver).json()
    assert approved["status"] == "active"
    assert [r["code"] for r in approved["rules_to_review"]] == ["COMPLAINT_ACK_SLA"]
    db.expire_all()
    old = db.get(PolicyVersion, current.id)
    assert old.status == "superseded" and old.effective_to is not None

    # New rule versions can only link to a policy version that is in force or still being drafted.
    rule = db.scalar(
        select(MistakeRule).where(MistakeRule.rule_code == "COMPLAINT_ACK_SLA", MistakeRule.status == "active")
    )
    stale = _rule_body(
        db,
        {"from_rule_id": rule.id},
        {"conditions": [{"field": "ack_business_days", "op": "gt", "value": 1}]},
        category="complaint_handling",
    )
    stale["policy_version_id"] = current.id
    assert client.post("/api/rules", json=stale, headers=author).json()["detail"]["errors"] == {
        "policy_version_id": "invalid"
    }


def test_upgrade_backfills_identical_facts(db):
    upgrade.backfill_attributes(db)  # clear anything other tests created without facts
    upgrade.backfill_matched_conditions(db)
    db.commit()
    # Other tests attach ad-hoc findings to arbitrary cases, so compare seeded ones only.
    case = db.scalar(select(ServiceCase).where(~ServiceCase.findings.any()).limit(1))
    finding = db.scalar(select(Finding).where(Finding.reason_code == "KYC_DOC_CHECK").limit(1))
    expected_case, expected_finding = case.attributes, finding.matched_conditions
    db.execute(update(ServiceCase).where(ServiceCase.id == case.id).values(attributes=None))
    db.execute(update(Finding).where(Finding.id == finding.id).values(matched_conditions=None))
    db.commit()
    assert upgrade.ensure_roles(db) == []  # seeded databases already have every role and grant
    assert upgrade.backfill_attributes(db) == 1
    assert upgrade.backfill_matched_conditions(db) == 1
    db.commit()
    db.expire_all()
    assert db.get(ServiceCase, case.id).attributes == expected_case
    assert db.get(Finding, finding.id).matched_conditions == expected_finding
