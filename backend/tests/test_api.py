from datetime import timedelta

from sqlalchemy import select

from app.db import new_id, utcnow
from app.models import AuditEvent, EmployeeProfile, Finding, MistakeRule, OrgUnit, ServiceCase, User
from app.services.rbac import descendants
from tests.conftest import PASSWORD


def _potential_finding_for(db, employee_id: str) -> Finding:
    """Create a fresh POTENTIAL finding on one of the employee's cases."""
    case = db.scalar(select(ServiceCase).where(ServiceCase.employee_id == employee_id).limit(1))
    rule = db.scalar(select(MistakeRule).where(MistakeRule.category == case.case_type, MistakeRule.status == "active"))
    finding = Finding(
        id=new_id("FND"),
        case_id=case.id,
        rule_id=rule.id,
        status="POTENTIAL",
        severity=rule.severity,
        reason_code=rule.rule_code,
        observed_action="obs",
        observed_action_ar="obs",
        explanation="exp",
        explanation_ar="exp",
        confidence=0.8,
    )
    db.add(finding)
    db.commit()
    return finding


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True


def test_login_rejects_bad_password_and_audits(client, db):
    response = client.post("/api/auth/login", json={"username": "superadmin", "password": "wrong"})
    assert response.status_code == 401
    denied = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login", AuditEvent.outcome == "denied"))
    assert denied is not None
    assert "password" not in denied.metadata_redacted


def test_logout_revokes_session(client):
    token = client.post("/api/auth/login", json={"username": "analyst", "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/dashboard/summary").status_code == 401
    assert client.get("/api/cases", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_employee_sees_only_own_cases(client, login, db):
    me = client.get("/api/auth/me", headers=login("employee.demo")).json()
    items = client.get("/api/cases?page_size=100", headers=login("employee.demo")).json()["items"]
    assert items, "demo employee should have findings"
    assert {i["employee"]["id"] for i in items} == {me["employee_id"]}

    other = db.scalar(select(ServiceCase).where(ServiceCase.employee_id != me["employee_id"]).limit(1))
    assert client.get(f"/api/cases/{other.id}", headers=login("employee.demo")).status_code == 404


def test_branch_manager_scope_is_limited_to_branch(client, login, db):
    branch = db.scalar(select(OrgUnit).where(OrgUnit.code == "BR-N01"))
    allowed = descendants(db, {branch.id})
    items = client.get("/api/cases?page_size=100", headers=login("branch.n01")).json()["items"]
    assert items and all(i["org_unit"]["id"] in allowed for i in items)


def test_data_ops_cannot_read_case_content(client, login):
    assert client.get("/api/cases", headers=login("data.ops")).status_code == 403
    assert client.get("/api/pipelines/status", headers=login("data.ops")).status_code == 200


def test_restricted_evidence_hidden_from_team_lead(client, login):
    item = client.get("/api/cases?page_size=1", headers=login("lead.br-n01-tel")).json()["items"][0]
    detail = client.get(f"/api/cases/{item['case_id']}", headers=login("lead.br-n01-tel")).json()
    restricted = [e for e in detail["evidence"] if e["access_class"] == "restricted"]
    assert restricted and all(e["secure_reference"] is None for e in restricted)


def test_review_response_and_action_workflow(client, login, db):
    employee = db.scalar(
        select(EmployeeProfile).join(User, User.id == EmployeeProfile.user_id).where(User.username == "employee.demo")
    )
    finding = _potential_finding_for(db, employee.id)
    emp, manager = login("employee.demo"), login("branch.n01")

    # After-feedback response is not possible before a reviewer has given feedback.
    early = client.post(
        f"/api/findings/{finding.id}/employee-response",
        json={"stage": "after_feedback", "understood_after_feedback": True},
        headers=emp,
    )
    assert early.status_code == 409

    before = client.post(
        f"/api/findings/{finding.id}/employee-response",
        json={"stage": "before_feedback", "awareness_state": "unsure", "contextual_factors": ["queue_pressure"]},
        headers=emp,
    )
    assert before.status_code == 200

    # Managers cannot respond on the employee's behalf.
    assert (
        client.post(
            f"/api/findings/{finding.id}/employee-response",
            json={"stage": "before_feedback", "awareness_state": "recognized"},
            headers=manager,
        ).status_code
        == 403
    )

    review = client.post(
        f"/api/findings/{finding.id}/review",
        json={
            "decision": "confirm",
            "rationale": "Evidence supports the finding.",
            "contributing_factor": "individual_action",
            "policy_clear": True,
        },
        headers=manager,
    )
    assert review.status_code == 200 and review.json()["status"] == "CONFIRMED"

    after = client.post(
        f"/api/findings/{finding.id}/employee-response",
        json={"stage": "after_feedback", "understood_after_feedback": True},
        headers=emp,
    )
    assert after.status_code == 200

    due = (utcnow() + timedelta(days=14)).isoformat()
    created = client.post(
        f"/api/findings/{finding.id}/actions",
        json={"action_type": "coaching", "description": "Coaching on read-back", "due_at": due},
        headers=manager,
    )
    assert created.status_code == 201
    action_id = created.json()["id"]

    no_evidence = client.patch(f"/api/actions/{action_id}", json={"status": "completed"}, headers=emp)
    assert no_evidence.status_code == 422
    done = client.patch(
        f"/api/actions/{action_id}",
        json={"status": "completed", "completion_evidence_ref": "lms://completion/test"},
        headers=emp,
    )
    assert done.status_code == 200
    assert client.patch(f"/api/actions/{action_id}", json={"status": "planned"}, headers=emp).status_code == 409

    history = client.get(f"/api/employees/{employee.id}/learning-history", headers=emp).json()
    assert history["live_evaluation"]["method_version"] == "demo-1.0"
    assert history["viewer"]["can_approve"] is False


def test_dispute_moves_finding_to_disputed(client, login, db):
    employee = db.scalar(
        select(EmployeeProfile).join(User, User.id == EmployeeProfile.user_id).where(User.username == "employee.demo")
    )
    finding = _potential_finding_for(db, employee.id)
    response = client.post(
        f"/api/findings/{finding.id}/employee-response",
        json={
            "stage": "before_feedback",
            "awareness_state": "disagree",
            "requested_review": True,
            "response_text": "Guidance was unclear.",
        },
        headers=login("employee.demo"),
    )
    assert response.json()["finding_status"] == "DISPUTED"


def test_employee_cannot_approve_own_generation(client, login):
    assert (
        client.post(
            "/api/learning-generations/GEN-NOPE/decision", json={"decision": "approve"}, headers=login("employee.demo")
        ).status_code
        == 403
    )


def test_simulation_is_illustrative_and_employee_level_disabled(client, login):
    headers = login("hr.ld")
    result = client.post(
        "/api/simulations",
        json={"case_type": "transfers", "interventions": ["coaching", "system_fix"]},
        headers=headers,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["illustrative"] is True and "illustrative_only" in body["limitations"]
    assert [o["intervention"] for o in body["options"]] == ["none", "coaching", "system_fix"]
    for option in body["options"]:
        low, high = option["interval_90"]
        assert low <= option["estimated_rate"] <= high

    blocked = client.post(
        "/api/simulations",
        json={"case_type": "transfers", "interventions": ["coaching"], "employee_id": "EMP-ANY"},
        headers=headers,
    )
    assert blocked.status_code == 403


def test_insights_respect_privacy_threshold(client, login):
    body = client.get("/api/insights/teams?level=section", headers=login("analyst")).json()
    for group in body["groups"]:
        if group["suppressed"]:
            assert "confirmed" not in group and group["employees"] is None


def test_reports_csv_export_is_labelled_synthetic(client, login):
    response = client.get("/api/reports/common-issues?format=csv", headers=login("risk.compliance"))
    assert response.status_code == 200
    assert response.text.startswith("# SYNTHETIC DEMO DATA")


def test_ops_reports_require_ops_permission(client, login):
    assert client.get("/api/reports/data-quality", headers=login("analyst")).status_code == 403
    assert client.get("/api/reports/data-quality", headers=login("data.ops")).status_code == 200


def test_unapproved_source_cannot_be_resumed(client, login):
    pipelines = client.get("/api/pipelines/status", headers=login("data.ops")).json()["pipelines"]
    transcripts = next(p for p in pipelines if p["code"] == "transcripts")
    response = client.post(f"/api/pipelines/{transcripts['id']}/resume", headers=login("data.ops"))
    assert response.status_code == 409


def test_admin_requires_super_admin(client, login):
    assert client.get("/api/admin/users", headers=login("branch.n01")).status_code == 403
    users = client.get("/api/admin/users", headers=login("superadmin")).json()
    assert any(u["username"] == "superadmin" for u in users)
