"""Configuration API: permissions, settings validation and effect, connection secrets."""

from sqlalchemy import select

from app.models import AuditEvent, DbConnection
from app.services import dbschema, learning, secrets, settings_store

CONN = {
    "name": "Bank pilot DB",
    "host": "db.pilot.example",
    "port": 5432,
    "database": "bop_evolve",
    "username": "bop_app",
    "password": "S3cret-pass!",
    "sslmode": "require",
    "schema_name": "public",
}


def test_only_super_admin_can_change_configuration(client, login):
    assert client.get("/api/config/settings", headers=login("branch.n01")).status_code == 403
    assert client.get("/api/config/settings", headers=login("data.ops")).status_code == 200  # view only
    put = client.put(
        "/api/config/settings", json={"values": {"privacy.min_group_cases": 12}}, headers=login("data.ops")
    )
    assert put.status_code == 403
    assert client.post("/api/config/db-connections", json=CONN, headers=login("data.ops")).status_code == 403


def test_settings_validation_errors(client, login):
    headers = login("superadmin")
    bad = client.put("/api/config/settings", json={"values": {"privacy.min_group_cases": 0}}, headers=headers)
    assert bad.status_code == 422
    assert bad.json()["detail"]["errors"]["privacy.min_group_cases"]["code"] == "out_of_range"
    weights = client.put("/api/config/settings", json={"values": {"learning.weight_follow_up": 0.5}}, headers=headers)
    assert weights.status_code == 422
    assert weights.json()["detail"]["errors"]["learning.weight_follow_up"]["code"] == "weights_sum"
    unknown = client.put("/api/config/settings", json={"values": {"nope.key": 1}}, headers=headers)
    assert unknown.json()["detail"]["errors"]["nope.key"]["code"] == "unknown"


def test_privacy_threshold_override_takes_effect_and_is_audited(client, login, db):
    headers = login("superadmin")
    put = client.put("/api/config/settings", json={"values": {"privacy.min_group_employees": 50}}, headers=headers)
    assert put.status_code == 200 and put.json()["changed"] == ["privacy.min_group_employees"]
    insights = client.get("/api/insights/teams?level=branch", headers=login("analyst")).json()
    assert insights["privacy"]["min_employees"] == 50
    assert all(group["suppressed"] for group in insights["groups"])
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "config.settings_update"))
    assert event.metadata_redacted["changes"]["privacy.min_group_employees"]["to"] == 50

    reset = client.delete("/api/config/settings/privacy.min_group_employees", headers=headers)
    assert reset.status_code == 200
    assert (
        client.get("/api/insights/teams?level=branch", headers=login("analyst")).json()["privacy"]["min_employees"] == 3
    )


def test_learning_weights_change_the_method_version(client, login, db):
    headers = login("superadmin")
    body = {
        "values": {
            "learning.weight_understanding": 0.3,
            "learning.weight_action_completion": 0.2,
            "learning.weight_follow_up": 0.3,
            "learning.weight_recurrence_trend": 0.2,
        }
    }
    put = client.put("/api/config/settings", json=body, headers=headers)
    assert put.status_code == 200
    version = put.json()["learning_method_version"]
    assert version.startswith(learning.METHOD_VERSION + "+")
    cfg = settings_store.learning_config(db)
    assert cfg.weights["understanding"] == 0.3 and cfg.method_version == version
    # Resetting one weight resets the whole set (they must keep summing to 1).
    reset = client.delete("/api/config/settings/learning.weight_follow_up", headers=headers)
    assert reset.status_code == 200 and len(reset.json()["changed"]) == 4
    assert settings_store.learning_config(db).method_version == learning.METHOD_VERSION


def test_connection_password_is_encrypted_and_never_returned(client, login, db):
    headers = login("superadmin")
    created = client.post("/api/config/db-connections", json=CONN, headers=headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["password_source"] == "stored" and "password" not in body and "S3cret" not in created.text
    row = db.get(DbConnection, body["id"])
    assert row.password_encrypted and "S3cret" not in row.password_encrypted
    assert secrets.decrypt(row.password_encrypted) == CONN["password"]

    listed = client.get("/api/config/db-connections", headers=headers)
    assert listed.json()[0]["id"] == dbschema.CURRENT_ID and "S3cret" not in listed.text

    # Updating without a password keeps the stored one.
    update = client.put(
        f"/api/config/db-connections/{body['id']}", json={**CONN, "password": None, "port": 6432}, headers=headers
    )
    assert update.status_code == 200
    db.expire_all()
    assert secrets.decrypt(db.get(DbConnection, body["id"]).password_encrypted) == CONN["password"]

    audit_text = " ".join(str(e.metadata_redacted) for e in db.scalars(select(AuditEvent)))
    assert "S3cret" not in audit_text
    assert client.delete(f"/api/config/db-connections/{body['id']}", headers=headers).status_code == 200


def test_password_env_reference_must_use_the_reserved_prefix(client, login):
    headers = login("superadmin")
    leak = client.post(
        "/api/config/db-connections",
        json={**CONN, "name": "x", "password": None, "password_env": "JWT_SECRET"},
        headers=headers,
    )
    assert leak.status_code == 422
    ok = client.post(
        "/api/config/db-connections",
        json={**CONN, "name": "Env ref", "password": None, "password_env": "BOP_DBPASS_PILOT"},
        headers=headers,
    )
    assert ok.status_code == 201 and ok.json()["password_source"] == "env"
    missing = client.post(f"/api/config/db-connections/{ok.json()['id']}/test", headers=headers)
    assert missing.status_code == 422 and "BOP_DBPASS_PILOT" in missing.json()["detail"]
    client.delete(f"/api/config/db-connections/{ok.json()['id']}", headers=headers)


def test_host_allowlist(monkeypatch):
    settings = dbschema.get_settings()
    monkeypatch.setattr(settings, "db_connection_allowed_hosts", "db.internal,*.bank.local")
    assert dbschema.host_allowed("db.internal")
    assert dbschema.host_allowed("pg01.bank.local")
    assert not dbschema.host_allowed("evil.example.com")
    monkeypatch.setattr(settings, "db_connection_allowed_hosts", "")
    monkeypatch.setattr(settings, "app_env", "production")
    assert not dbschema.host_allowed("db.internal")


def test_current_database_check_and_apply_permissions(client, login):
    check = client.post("/api/config/db-connections/current/schema-check", headers=login("data.ops"))
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "valid"  # the test database is created from the same models
    assert body["can_apply"] is False and "app_permission" in body["blockers"]
    assert {t["status"] for t in body["tables"]} == {"ok"}
    apply = client.post(
        "/api/config/db-connections/current/apply",
        json={"plan_hash": body["plan_hash"], "confirm_database": "x"},
        headers=login("data.ops"),
    )
    assert apply.status_code == 403


def test_apply_requires_typed_confirmation(client, login):
    headers = login("superadmin")
    check = client.post("/api/config/db-connections/current/schema-check", headers=headers).json()
    wrong = client.post(
        "/api/config/db-connections/current/apply",
        json={"plan_hash": check["plan_hash"], "confirm_database": "not-the-db"},
        headers=headers,
    )
    assert wrong.status_code == 422


def test_pipeline_schedule_update(client, login):
    headers = login("superadmin")
    pipelines = client.get("/api/config/pipelines", headers=headers).json()
    target = pipelines[0]
    bad = client.patch(f"/api/config/pipelines/{target['id']}", json={"schedule_seconds": 5}, headers=headers)
    assert bad.status_code == 422
    ok = client.patch(f"/api/config/pipelines/{target['id']}", json={"schedule_seconds": 600}, headers=headers)
    assert ok.status_code == 200 and ok.json()["changed"] == ["schedule_seconds"]


def test_public_settings_and_environment(client, login):
    assert client.get("/api/public/settings").json() == {"default_locale": "en"}
    env = client.get("/api/config/environment", headers=login("superadmin")).json()
    assert env["alembic_head"] == dbschema.head_revision()
    assert "password" not in str(env["database"]).lower()
