"""Onboarding: roster import, grade-based access, waves, activation codes and the welcome journey."""

import csv
import io

from sqlalchemy import select

from app.models import EmployeeProfile, OnboardingInvite, OrgUnit, Role, User, UserRole
from app.services import onboarding


def _chief(client):
    token = client.post("/api/auth/login", json={"username": "hr.chief", "password": "123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(onboarding.COLUMNS))
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in onboarding.COLUMNS})
    return out.getvalue()


def test_sample_roster_is_bank_sized_and_valid(db):
    text = onboarding.sample_roster(3400)
    rows, _ = onboarding.parse_csv(text)
    assert len(rows) == 3400
    valid, errors, summary = onboarding.validate(db, rows)
    assert errors == [] and len(valid) == 3400
    assert {"C", "D", "RM", "BM", "SM", "TL", "O"} <= set(summary["by_grade"])
    assert summary["by_role"]["employee"] > 2500 and summary["by_role"]["hr_chief"] >= 1
    assert summary["new_unit_count"] > 100  # branches and sections beyond the demo's eight branches
    db.rollback()


def test_validation_reports_row_errors_without_writing(client, db):
    headers = _chief(client)
    before = db.scalar(select(User.id).where(User.username == "900001"))
    rows = [
        {
            "employee_number": "900001",
            "full_name": "Test Officer",
            "grade": "O",
            "job_title": "Teller",
            "department_code": "DEP-RETAIL",
            "region_code": "REG-NORTH",
            "branch_code": "BR-N01",
            "section_code": "BR-N01-TEL",
        },
        {
            "employee_number": "900001",
            "full_name": "Duplicate",
            "grade": "O",
            "job_title": "Teller",
            "department_code": "DEP-RETAIL",
        },
        {
            "employee_number": "900002",
            "full_name": "Bad grade",
            "grade": "ZZ",
            "job_title": "x",
            "department_code": "DEP-RETAIL",
        },
        {
            "employee_number": "900003",
            "full_name": "Wrong parent",
            "grade": "O",
            "job_title": "x",
            "department_code": "DEP-CC",
            "branch_code": "BR-N01",
        },
        {
            "employee_number": "900004",
            "full_name": "Manager missing branch",
            "grade": "BM",
            "job_title": "x",
            "department_code": "DEP-RETAIL",
            "region_code": "REG-NORTH",
        },
        {
            "employee_number": "900005",
            "full_name": "Bad time",
            "grade": "O",
            "job_title": "x",
            "department_code": "DEP-RETAIL",
            "work_start": "25:00",
        },
    ]
    response = client.post(
        "/api/onboarding/imports", json={"file_name": "t.csv", "content": _csv(rows)}, headers=headers
    )
    assert response.status_code == 201, response.text
    data = response.json()
    codes = {(e["employee_number"], e["field"], e["code"]) for e in data["errors"]}
    assert ("900001", "employee_number", "duplicate_in_file") in codes
    assert ("900002", "grade", "unknown_grade") in codes
    assert ("900003", "branch_code", "unit_parent_mismatch") in codes
    assert ("900004", "branch_code", "required_for_grade") in codes
    assert ("900005", "work_start", "invalid_time") in codes
    assert data["valid_rows"] == 0 and data["status"] == "failed"
    assert db.scalar(select(User.id).where(User.username == "900001")) == before is None
    missing = client.post("/api/onboarding/imports", json={"content": "name,grade\nx,O\n"}, headers=headers)
    assert missing.status_code == 422


def test_import_waves_activation_and_journey(client, login, db):
    headers = _chief(client)
    roster = onboarding.sample_roster(80)
    imported = client.post(
        "/api/onboarding/imports", json={"file_name": "roster.csv", "content": roster}, headers=headers
    )
    assert imported.status_code == 201, imported.text
    record = imported.json()
    assert record["errors"] == [] and record["valid_rows"] == 80 and record["summary"]["to_create"] == 80
    committed = client.post(f"/api/onboarding/imports/{record['id']}/commit", headers=headers)
    assert committed.status_code == 200, committed.text
    assert committed.json()["created_count"] == 80
    assert client.post(f"/api/onboarding/imports/{record['id']}/commit", headers=headers).status_code == 409

    # Grade decides access: the CEO row (grade C, DEP-OPS) is a department head; officers are self-service.
    first = next(csv.DictReader(io.StringIO(roster)))
    ceo = db.scalar(select(User).where(User.username == first["employee_number"]))
    assert ceo.status == "invited" and ceo.password_hash is None
    grants = {
        (code, scope)
        for code, scope in db.execute(
            select(Role.code, UserRole.scope_type)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == ceo.id)
        )
    }
    assert grants == {("dept_head", "department"), ("employee", "self")}
    hr_head = db.scalar(select(EmployeeProfile).where(EmployeeProfile.role_title == "Head of Human Resources"))
    hr_roles = set(
        db.scalars(
            select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == hr_head.user_id)
        )
    )
    assert "hr_chief" in hr_roles
    profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == ceo.id))
    assert profile.pseudonym.startswith("E-") and profile.external_ref not in profile.pseudonym
    assert db.scalar(select(OrgUnit).where(OrgUnit.code == "DEP-HR")).name == "Human Resources"
    # Invited accounts cannot sign in and are not offered on the login screen.
    assert client.post("/api/auth/login", json={"username": ceo.username, "password": "x"}).status_code == 401
    demo = client.get("/api/auth/demo-accounts").json()
    assert all(a["username"] != ceo.username for a in demo)

    # Re-importing the same roster updates instead of duplicating.
    again = client.post("/api/onboarding/imports", json={"content": roster}, headers=headers).json()
    assert again["summary"]["to_update"] == 80 and again["summary"]["to_create"] == 0

    # Wave for HR department, launched: one-time codes come back once as CSV.
    hr = db.scalar(select(OrgUnit).where(OrgUnit.code == "DEP-HR"))
    body = {"name": "Wave 1 - Human Resources", "unit_ids": [hr.id], "grades": [], "starts_on": "2026-11-01"}
    preview = client.post("/api/onboarding/waves/preview", json=body, headers=headers).json()
    assert preview["count"] > 5
    wave = client.post("/api/onboarding/waves", json=body, headers=headers).json()
    launched = client.post(f"/api/onboarding/waves/{wave['id']}/launch", headers=headers)
    assert launched.status_code == 200 and launched.headers["x-codes-issued"] == str(preview["count"])
    codes = list(csv.DictReader(io.StringIO(launched.text)))
    assert len(codes) == preview["count"] and all(len(c["activation_code"]) == 11 for c in codes)
    stored = db.scalars(select(OnboardingInvite.code_hash)).all()
    assert all(c["activation_code"] not in stored for c in codes)  # only hashes are stored

    person = codes[0]
    bad = client.post(
        "/api/auth/activate", json={"username": person["username"], "code": "AAAAA-BBBBB", "password": "Welcome2026"}
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_code"
    weak = client.post(
        "/api/auth/activate",
        json={"username": person["username"], "code": person["activation_code"], "password": "short"},
    )
    assert weak.status_code == 422
    ok = client.post(
        "/api/auth/activate",
        json={"username": person["username"], "code": person["activation_code"], "password": "Welcome2026"},
    )
    assert ok.status_code == 200, ok.text
    me = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (
        client.post(
            "/api/auth/activate",
            json={"username": person["username"], "code": person["activation_code"], "password": "Welcome2026"},
        ).status_code
        == 400
    )
    assert (
        client.post("/api/auth/login", json={"username": person["username"], "password": "Welcome2026"}).status_code
        == 200
    )

    journey = client.get("/api/onboarding/me", headers=me).json()
    assert journey["steps"][0]["done_at"] and not journey["completed_at"]
    assert {p["code"] for p in journey["policies"]} >= {"HR-01", "HR-02", "HR-03"}
    client.post("/api/onboarding/me/language", json={"locale": "ar"}, headers=me)
    client.post("/api/onboarding/me/tour", headers=me)
    acked = client.post(
        "/api/onboarding/me/acknowledge",
        json={"policy_version_ids": [p["id"] for p in journey["policies"]]},
        headers=me,
    ).json()
    assert acked["steps"][3]["done_at"]
    quiz = client.get("/api/onboarding/me/quiz?language=ar", headers=me).json()
    assert quiz["source"] == "built_in" and len(quiz["questions"]) == 3
    assert all("answer_index" not in q for q in quiz["questions"])
    wrong = client.post(
        "/api/onboarding/me/quiz", json={"quiz_id": quiz["quiz_id"], "answers": [3, 3, 3]}, headers=me
    ).json()
    assert not wrong["passed"] and not wrong["journey"]["completed_at"]
    right = [r["correct_index"] for r in wrong["review"]]
    passed = client.post(
        "/api/onboarding/me/quiz", json={"quiz_id": quiz["quiz_id"], "answers": right}, headers=me
    ).json()
    assert passed["passed"] and passed["journey"]["completed_at"] and passed["score"] == 3

    # HR sees the funnel and the people list; others do not.
    overview = client.get("/api/onboarding/overview", headers=headers).json()
    assert overview["funnel"]["roster"] == 80 and overview["funnel"]["completed"] == 1
    assert overview["funnel"]["invited"] == preview["count"]
    assert any(w["id"] == wave["id"] for w in overview["waves"])
    done = client.get("/api/onboarding/people?stage=completed", headers=headers).json()
    assert done["total"] == 1 and done["items"][0]["employee_number"] == person["employee_number"]
    waiting = client.get(f"/api/onboarding/people?stage=invited&wave_id={wave['id']}", headers=headers).json()
    assert waiting["total"] == preview["count"] - 1
    reminder = client.post(
        f"/api/onboarding/waves/{wave['id']}/reminder",
        json={"message": "Please finish your BOP Evolve welcome steps this week."},
        headers=headers,
    ).json()
    assert reminder["recipients"] == preview["count"] - 1
    assert client.get("/api/onboarding/overview", headers=login("branch.n01")).status_code == 403

    # The new account's own records are self-scoped (workplace view of themselves only).
    mine = client.get("/api/workplace/overview", headers=me)
    assert mine.status_code == 200


def test_activation_locks_after_repeated_wrong_codes(client, db):
    headers = _chief(client)
    rows = [
        {
            "employee_number": "910001",
            "full_name": "Lock Test",
            "grade": "O",
            "job_title": "Officer",
            "department_code": "DEP-OPS",
        }
    ]
    record = client.post("/api/onboarding/imports", json={"content": _csv(rows)}, headers=headers).json()
    client.post(f"/api/onboarding/imports/{record['id']}/commit", headers=headers)
    ops = db.scalar(select(OrgUnit).where(OrgUnit.code == "DEP-OPS"))
    wave = client.post(
        "/api/onboarding/waves",
        json={"name": "Lock wave", "unit_ids": [ops.id], "grades": ["O"], "starts_on": "2026-11-02"},
        headers=headers,
    ).json()
    codes = list(
        csv.DictReader(io.StringIO(client.post(f"/api/onboarding/waves/{wave['id']}/launch", headers=headers).text))
    )
    mine = next(c for c in codes if c["username"] == "910001")
    for _ in range(onboarding.MAX_ACTIVATION_ATTEMPTS):
        client.post("/api/auth/activate", json={"username": "910001", "code": "WRONG-CODE1", "password": "Welcome2026"})
    locked = client.post(
        "/api/auth/activate", json={"username": "910001", "code": mine["activation_code"], "password": "Welcome2026"}
    )
    assert locked.status_code == 400


def test_worker_simulates_time_clock_for_imported_staff_in_batches(db, monkeypatch):
    from sqlalchemy import func

    from app.models import AttendanceDay
    from app.pipeline import worker

    imported = select(EmployeeProfile.id).where(EmployeeProfile.external_ref.is_not(None))
    assert (
        db.scalar(select(func.count()).select_from(AttendanceDay).where(AttendanceDay.employee_id.in_(imported))) == 0
    )
    monkeypatch.setattr(worker, "TIME_CLOCK_BATCH", 500)
    assert worker.simulate_time_clock(db) == 500
    db.commit()
    total = 500
    while written := worker.simulate_time_clock(db):
        db.commit()
        total += written
    assert total > 1000  # ~80 people x ~26 working days, less people starting later
    assert worker.simulate_time_clock(db) == 0
