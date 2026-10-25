"""Schema validation and migration against real PostgreSQL databases.

Runs only when TEST_PG_ADMIN_URL points at a PostgreSQL server where the user may
create databases and roles, e.g. postgresql://bop:bop@localhost:5432/postgres
"""

import os
import secrets as pysecrets

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.services import dbschema

ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_PG_ADMIN_URL not set")


def _admin_engine():
    url = make_url(ADMIN_URL).set(drivername="postgresql+psycopg")
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture
def target_db():
    name = f"bop_schema_{pysecrets.token_hex(4)}"
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(drivername="postgresql+psycopg", database=name)
    yield name, url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _target(url, schema="public"):
    return dbschema.Target(key="test", name="test", url=url, schema=schema)


def _sql(url, *statements):
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
    engine.dispose()


def _by_kind(result):
    return {(c["kind"], c["table"], c["column"]): c for c in result["plan"]}


def test_empty_database_is_created_and_stamped(target_db):
    _, url = target_db
    result = dbschema.check_schema(_target(url))
    assert result["status"] == "empty"
    assert result["summary"]["missing_tables"] == result["summary"]["expected_tables"]
    assert result["summary"]["changes"]["risky"] == 0

    outcome = dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=False)
    assert outcome["stamped_revision"] == dbschema.head_revision()
    assert outcome["check"]["status"] == "valid"
    assert outcome["check"]["revision"]["current"] == dbschema.head_revision()


def test_drift_is_classified_and_only_safe_changes_apply(target_db):
    _, url = target_db
    first = dbschema.check_schema(_target(url))
    dbschema.apply_changes(_target(url), first["plan_hash"], include_risky=False)
    _sql(
        url,
        "INSERT INTO users (id, username, display_name, locale, status, created_at) "
        "VALUES ('USR-1', 'u1', 'User', 'en', 'active', now())",
        "ALTER TABLE findings DROP COLUMN confidence",  # nullable, missing -> safe
        "DROP INDEX ix_findings_status",  # missing index -> safe
        "ALTER TABLE users ALTER COLUMN display_name TYPE TEXT",  # type drift -> risky
        "ALTER TABLE users DROP COLUMN locale",  # NOT NULL on a table with rows -> blocked
        "ALTER TABLE roles ADD COLUMN legacy_flag INTEGER",  # extra column -> destructive
        "CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY)",  # extra table -> destructive
    )

    result = dbschema.check_schema(_target(url))
    assert result["status"] == "invalid"
    plan = _by_kind(result)
    assert plan[("missing_column", "findings", "confidence")]["category"] == "safe"
    assert ("missing_index", "findings", None) in plan
    assert plan[("column_differs", "users", "display_name")]["category"] == "risky"
    locale = plan[("missing_column", "users", "locale")]
    assert locale["category"] == "risky" and locale["allowed"] is False
    assert plan[("extra_column", "roles", "legacy_flag")]["category"] == "destructive"
    assert plan[("extra_table", "legacy_notes", None)]["allowed"] is False
    assert "legacy_notes" in result["extra_tables"]
    tables = {t["name"]: t["status"] for t in result["tables"]}
    assert tables["findings"] == "differs" and tables["roles"] == "differs" and tables["audit_events"] == "ok"

    # Risky changes include a blocked one, so including them is refused as a whole.
    with pytest.raises(dbschema.TargetError):
        dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=True)

    outcome = dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=False)
    applied = {a["description"] for a in outcome["applied"]}
    assert any("findings.confidence" in d for d in applied)
    after = outcome["check"]
    assert after["summary"]["changes"]["safe"] == 0
    assert after["summary"]["changes"]["risky"] == 2  # type change + blocked NOT NULL column
    assert after["summary"]["changes"]["destructive"] == 2  # never applied
    assert outcome["stamped_revision"] is None  # schema still differs, so no stamp

    # Extra objects are untouched.
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('legacy_notes')")).scalar() == "legacy_notes"
    engine.dispose()


def test_plan_must_match_the_last_check(target_db):
    _, url = target_db
    result = dbschema.check_schema(_target(url))
    _sql(url, "CREATE TABLE sneaky (id INTEGER)")
    with pytest.raises(dbschema.PlanChanged):
        dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=False)


def test_failed_change_rolls_back_everything(target_db):
    _, url = target_db
    result = dbschema.check_schema(_target(url))
    # Make one CREATE TABLE fail mid-plan by occupying the name with a view after the check.
    _sql(url, "CREATE VIEW org_units AS SELECT 1 AS x")
    with pytest.raises((dbschema.PlanChanged, dbschema.TargetError)):
        dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=False)
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('users')")).scalar() is None
    engine.dispose()


def test_privileges_block_changes_for_a_restricted_account(target_db):
    name, url = target_db
    first = dbschema.check_schema(_target(url))
    dbschema.apply_changes(_target(url), first["plan_hash"], include_risky=False)
    role = f"bop_ro_{pysecrets.token_hex(3)}"
    password = pysecrets.token_hex(8)
    _sql(
        url,
        f"CREATE ROLE {role} LOGIN PASSWORD '{password}'",
        f'GRANT CONNECT ON DATABASE "{name}" TO {role}',
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"REVOKE CREATE ON SCHEMA public FROM {role}",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        "ALTER TABLE findings DROP COLUMN confidence",
    )
    try:
        limited = _target(url.set(username=role, password=password))
        test = dbschema.test_connection(limited)
        assert test["ok"] and test["privileges"]["superuser"] is False
        assert test["privileges"]["can_create_tables"] is False

        result = dbschema.check_schema(limited)
        change = _by_kind(result)[("missing_column", "findings", "confidence")]
        assert change["allowed"] is False and "does not own" in change["reason"]
        with pytest.raises(dbschema.TargetError):
            dbschema.apply_changes(limited, result["plan_hash"], include_risky=False)
    finally:
        _sql(url, f"DROP OWNED BY {role}", f"DROP ROLE {role}")


def test_missing_schema_is_reported(target_db):
    _, url = target_db
    result = dbschema.check_schema(_target(url, schema="does_not_exist"))
    assert result["status"] == "error" and "does_not_exist" in result["error"]


def test_bad_credentials_are_reported_without_secrets(target_db):
    _, url = target_db
    result = dbschema.test_connection(_target(url.set(password="definitely-wrong")))
    assert result["ok"] is False
    assert "definitely-wrong" not in result["error"]


def test_matching_but_unstamped_database_can_be_stamped(target_db):
    _, url = target_db
    first = dbschema.check_schema(_target(url))
    dbschema.apply_changes(_target(url), first["plan_hash"], include_risky=False)
    _sql(url, "DROP TABLE alembic_version")  # tables match, revision unknown (hand-built database)
    result = dbschema.check_schema(_target(url))
    assert result["status"] == "valid" and "not_stamped" in result["warnings"]
    assert dbschema.needs_stamp(result)
    outcome = dbschema.apply_changes(_target(url), result["plan_hash"], include_risky=False)
    assert outcome["applied"] == [] and outcome["stamped_revision"] == dbschema.head_revision()
    assert not dbschema.needs_stamp(outcome["check"])
