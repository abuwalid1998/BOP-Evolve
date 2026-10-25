"""Chief HR Officer: account, workforce view, employee report and the repeat-risk model."""

from sqlalchemy import select

from app.models import AuditEvent, EmployeeProfile, OrgUnit
from app.services import workforce


def _chief(client):
    response = client.post("/api/auth/login", json={"username": "hr.chief", "password": "123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chief_signs_in_with_own_password_and_has_bank_wide_view(client, login):
    assert client.post("/api/auth/login", json={"username": "hr.chief", "password": "wrong"}).status_code == 401
    headers = _chief(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["roles"][0]["code"] == "hr_chief" and "workforce.view" in me["permissions"]
    assert "cases.view" in me["permissions"] and "config.manage" not in me["permissions"]
    # Other roles do not see individual workforce data.
    for user in ("hr.ld", "analyst", "branch.n01", "employee.demo"):
        assert client.get("/api/hr/workforce", headers=login(user)).status_code == 403


def test_workforce_view_groups_by_unit(client, db):
    headers = _chief(client)
    bank = client.get("/api/hr/workforce", headers=headers).json()
    total = db.scalar(select(EmployeeProfile.id).limit(1))
    assert total and bank["totals"]["employees"] == len(bank["employees"]) > 10
    assert {c["unit"]["type"] for c in bank["children"]} == {"department"}
    assert sum(c["employees"] for c in bank["children"]) == bank["totals"]["employees"]
    row = max(bank["employees"], key=lambda r: r["confirmed_12m"])
    assert row["confirmed_12m"] > 0 and row["last_finding_at"] and row["actions"]["total"] > 0
    assert row["top_outlook"]["band"] in ("low", "moderate", "elevated")
    assert bank["model"]["name"] == workforce.MODEL_NAME and bank["model"]["follow_ups"] > 0

    branch = db.scalar(select(OrgUnit).where(OrgUnit.code == "BR-N01"))
    scoped = client.get(f"/api/hr/workforce?unit_id={branch.id}", headers=headers).json()
    assert [b["code"] for b in scoped["breadcrumb"]][-1] == "BR-N01"
    assert {c["unit"]["type"] for c in scoped["children"]} == {"section"}
    assert all(any(p["code"] == "BR-N01" for p in r["path"]) for r in scoped["employees"])
    assert client.get("/api/hr/workforce?unit_id=ORG-missing", headers=headers).status_code == 404


def test_employee_report_contents_and_audit(client, db):
    headers = _chief(client)
    rows = client.get("/api/hr/workforce", headers=headers).json()["employees"]
    target = max(rows, key=lambda r: r["confirmed_12m"])
    report = client.get(f"/api/hr/employees/{target['id']}/report", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert body["employee"]["pseudonym"] == target["pseudonym"]
    assert len(body["monthly"]) == 12
    assert sum(m["confirmed"] for m in body["monthly"]) == body["summary"]["confirmed_12m"]
    reviewed = [t for t in body["timeline"] if t["decision"]]
    assert reviewed and reviewed[0]["decision"]["by"]["name"]
    with_actions = [t for t in body["timeline"] if t["actions"]]
    assert with_actions and with_actions[0]["actions"][0]["owner"]["role"]
    assert body["timeline"] == sorted(body["timeline"], key=lambda t: t["occurred_at"], reverse=True)
    for o in body["summary"]["outlook"]:
        assert 0 <= o["probability"] < 1 and o["recommendation"]
    assert client.post(f"/api/hr/employees/{target['id']}/report/printed", headers=headers).json() == {"recorded": True}
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == target["id"])))
    assert {"hr.report_viewed", "hr.report_printed"} <= actions
    assert client.get("/api/hr/employees/EMP-missing/report", headers=headers).status_code == 404


def test_model_learning_effects_are_estimated_from_follow_ups(db):
    model = workforce.fit_model(db, now=None)
    assert set(model.multipliers) == {"actions_completed", "actions_open", "understood", "not_understood"}
    assert all(0.4 <= m <= 2.5 for m in model.multipliers.values())
    # Learning evidence can only lower the estimate; its absence can only raise it.
    assert model.multipliers["actions_completed"] <= 1 <= model.multipliers["actions_open"]
    assert model.multipliers["understood"] <= 1 <= model.multipliers["not_understood"]
    assert 0.5 <= model.employee_strength <= 50
    assert all(0 <= r < 1 for r in model.peer_rate.values())
    assert workforce.band(0.05, 0.04) == "low"  # too unlikely to matter
    assert workforce.band(0.30, 0.40) == "low"  # better than peers with the same caseload
    assert workforce.band(0.40, 0.38) == "moderate"
    assert workforce.band(0.60, 0.35) == "elevated"
