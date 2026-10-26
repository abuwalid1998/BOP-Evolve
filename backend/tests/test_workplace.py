"""Workplace policies: attendance, breaks and dress code."""

from datetime import timedelta

from sqlalchemy import func, select

from app.db import utcnow
from app.models import AttendanceDay, EmployeeProfile, MistakeRule, OrgUnit, WorkplaceException
from app.services import rules_engine, workplace


def test_seed_has_simulated_history_and_rule_driven_exceptions(db):
    days = db.scalar(select(func.count()).select_from(AttendanceDay))
    assert days > 5000
    assert (
        db.scalar(select(func.count()).select_from(AttendanceDay).where(AttendanceDay.work_date >= utcnow().date()))
        == 0
    )
    # Every exception is a real rule match on its record.
    rules = {r.id: r for r in db.scalars(select(MistakeRule).where(MistakeRule.category == "attendance"))}
    sample = db.scalars(select(WorkplaceException).where(WorkplaceException.source_type == "attendance").limit(200))
    for x in sample:
        record = db.get(AttendanceDay, x.source_id)
        assert rules_engine.matches(rules[x.rule_id].conditions, workplace.attendance_facts(record))
    statuses = dict(
        db.execute(select(WorkplaceException.status, func.count()).group_by(WorkplaceException.status)).all()
    )
    assert {"open", "explained", "confirmed", "excused", "dismissed"} <= set(statuses)


def test_simulation_is_deterministic_and_consistent():
    profile = EmployeeProfile(
        id="EMP-X",
        pseudonym="E-TEST",
        org_unit_id="ORG-X",
        role_title="Teller",
        work_start_min=480,
        work_end_min=900,
        customer_facing=True,
    )
    today = utcnow().date()
    seen = []
    for i in range(1, 200):
        day = today - timedelta(days=i)
        a = workplace.simulate_day(profile, day, today, 60)
        b = workplace.simulate_day(profile, day, today, 60)
        assert (a.status, a.check_in_min, a.break_minutes) == (b.status, b.check_in_min, b.break_minutes)
        if a.status == "worked" and a.check_in_min is not None:
            assert a.minutes_late == max(0, a.check_in_min - 480)
            assert a.break_overrun_minutes == max(0, a.break_minutes - 60)
        seen.append(a.status)
    assert "worked" in seen


def test_hr_overview_kpis_drilldown_and_permissions(client, login):
    chief = client.post("/api/auth/login", json={"username": "hr.chief", "password": "123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {chief}"}
    bank = client.get("/api/workplace/overview?days=60", headers=headers)
    assert bank.status_code == 200, bank.text
    data = bank.json()
    k = data["kpis"]
    assert k["employees"] > 50 and 0.5 < k["punctuality_rate"] <= 1 and 0 < k["adherence_index"] <= 100
    assert k["lost_hours_per_employee_month"] > 0 and k["dress_observations"] > 0
    assert {c["unit"]["type"] for c in data["children"]} == {"department"}
    assert sum(c["kpis"]["days_worked"] for c in data["children"]) == k["days_worked"]
    assert data["weekly"] and data["weekday"] and data["by_rule"] and data["policies"]
    assert {p["code"] for p in data["policies"]} == {"HR-01", "HR-02", "HR-03"}
    region = next(c for c in data["children"] if c["unit"]["code"] == "DEP-RETAIL")["unit"]["id"]
    drill = client.get(f"/api/workplace/overview?unit_id={region}", headers=headers).json()
    assert drill["unit"]["code"] == "DEP-RETAIL" and {c["unit"]["type"] for c in drill["children"]} == {"region"}

    # A branch manager sees their branch only; an analyst sees nothing.
    branch = client.get("/api/workplace/overview", headers=login("branch.n01")).json()
    assert branch["unit"]["code"] == "BR-N01"
    assert client.get(f"/api/workplace/overview?unit_id={region}", headers=login("branch.n01")).status_code == 404
    assert client.get("/api/workplace/overview", headers=login("analyst")).status_code == 403


def test_employee_explains_and_supervisor_decides(client, login, db):
    me = client.get("/api/workplace/me", headers=login("employee.demo"))
    assert me.status_code == 200, me.text
    mine = me.json()
    assert mine["kpis"]["days_worked"] > 0 and mine["recent_days"]
    open_items = [x for x in mine["exceptions"] if x["can_respond"]]
    assert open_items, "the demo employee should have open exceptions"
    target = open_items[0]
    assert not target["can_decide"]
    explained = client.post(
        f"/api/workplace/exceptions/{target['id']}/respond",
        json={"reason_code": "transport", "reason_text": "Road closure at the checkpoint"},
        headers=login("employee.demo"),
    )
    assert explained.status_code == 200 and explained.json()["status"] == "explained"
    again = client.post(
        f"/api/workplace/exceptions/{target['id']}/respond",
        json={"reason_code": "other"},
        headers=login("employee.demo"),
    )
    assert again.status_code == 409

    # The team lead of the employee's section decides; an unrelated section manager cannot.
    unit = db.get(OrgUnit, db.get(WorkplaceException, target["id"]).org_unit_id)
    lead = f"lead.{unit.code.lower()}"
    queue = client.get("/api/workplace/exceptions?status=pending", headers=login(lead)).json()
    assert any(x["id"] == target["id"] and x["can_decide"] for x in queue["items"])
    decided = client.post(
        f"/api/workplace/exceptions/{target['id']}/decide",
        json={"decision": "excused", "note": "Known closure"},
        headers=login(lead),
    )
    assert decided.status_code == 200 and decided.json()["status"] == "excused" and decided.json()["action"] is None
    assert (
        client.post(
            f"/api/workplace/exceptions/{target['id']}/decide", json={"decision": "confirmed"}, headers=login(lead)
        ).status_code
        == 409
    )

    other = db.scalar(
        select(WorkplaceException).where(WorkplaceException.org_unit_id != unit.id, WorkplaceException.status == "open")
    )
    assert (
        client.post(
            f"/api/workplace/exceptions/{other.id}/decide", json={"decision": "confirmed"}, headers=login(lead)
        ).status_code
        == 404
    )
    # Employees cannot decide; supervisors cannot respond for staff.
    assert (
        client.post(
            f"/api/workplace/exceptions/{other.id}/decide",
            json={"decision": "confirmed"},
            headers=login("employee.demo"),
        ).status_code
        == 403
    )


def test_bulk_decide_and_observation_raises_dress_code_exception(client, login, db):
    lead = "lead.br-n01-tel"
    unit = db.scalar(select(OrgUnit).where(OrgUnit.code == "BR-N01-TEL"))
    pending = client.get(
        f"/api/workplace/exceptions?status=pending&unit_id={unit.id}&page_size=5", headers=login(lead)
    ).json()["items"]
    decidable = [x["id"] for x in pending if x["can_decide"]]
    result = client.post(
        "/api/workplace/exceptions/decide-bulk",
        json={"ids": [*decidable, "WEX-NOPE"], "decision": "confirmed", "action": "reminder"},
        headers=login(lead),
    ).json()
    assert result["decided"] == len(decidable) and {"id": "WEX-NOPE", "reason": 404} in result["skipped"]

    staff = client.get("/api/workplace/employees", headers=login(lead)).json()
    assert staff and all(e["id"] for e in staff)
    target = next(e for e in staff if db.get(EmployeeProfile, e["id"]).user_id is None)
    made = client.post(
        "/api/workplace/observations",
        json={"employee_id": target["id"], "item": "id_badge", "compliant": False, "note": "Badge at home"},
        headers=login(lead),
    )
    assert made.status_code == 201, made.text
    raised = made.json()["exceptions"]
    assert len(raised) == 1 and raised[0]["rule"]["code"] == "HR_DRESS_CODE" and raised[0]["status"] == "open"
    ok = client.post(
        "/api/workplace/observations",
        json={"employee_id": target["id"], "item": "formal_attire", "compliant": True},
        headers=login(lead),
    ).json()
    assert ok["exceptions"] == []
    # Observations are limited to staff in scope.
    far = db.scalar(select(EmployeeProfile).where(EmployeeProfile.org_unit_id != unit.id))
    assert (
        client.post(
            "/api/workplace/observations",
            json={"employee_id": far.id, "item": "id_badge", "compliant": False},
            headers=login(lead),
        ).status_code
        == 404
    )


def test_workplace_rules_backtest_through_rules_engine(client, login, db):
    rule = db.scalar(select(MistakeRule).where(MistakeRule.rule_code == "HR_LATE_ARRIVAL"))
    result = rules_engine.backtest(db, "attendance", rule.conditions, days=60)
    assert result["cases_evaluated"] > 1000 and result["matches"] > 0
    assert result["matched_reviewed"] > 0 and result["confirm_rate"] is not None
    stricter = {"match": "all", "conditions": [{"field": "minutes_late", "op": "gt", "value": 5}]}
    wider = rules_engine.backtest(db, "attendance", stricter, days=60, compare=rule.conditions)
    assert wider["matches"] >= result["matches"] and wider["comparison"]["only_current"] == 0
    # Workplace facts are not offered for customer-service types and vice versa.
    catalogue = client.get("/api/rules/catalogue", headers=login("ops.policy")).json()
    fields = {f["key"]: f for f in catalogue["fields"]}
    assert "attendance" not in fields["complexity_band"]["case_types"]
    assert fields["minutes_late"]["case_types"] == ["attendance"]
    assert {c["code"] for c in catalogue["case_types"] if c["domain"] == "workplace"} == {"attendance", "dress_code"}
    try:
        rules_engine.validate("attendance", {"conditions": [{"field": "complexity_band", "op": "eq", "value": "low"}]})
        raise AssertionError("service fact accepted for a workplace rule")
    except rules_engine.RuleError as exc:
        assert exc.errors == {"conditions.0.field": "not_for_case_type"}


def test_worker_backfill_is_idempotent(db):
    employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.external_ref.is_(None)))
    today = utcnow().date()
    assert workplace.backfill(db, [employee], 30, today, limit=500) == 0  # seeded already
    db.rollback()
