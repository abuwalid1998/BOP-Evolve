"""Database connections: test, validate the schema against the BOP Evolve model, and migrate safely.

The expected schema is the SQLAlchemy metadata (identical to the Alembic head,
which CI verifies). Alembic's autogenerate comparison produces the list of
operations that would make a target database match. Each operation is:

* ``safe``        additive (create table / column / index / constraint), offered by default;
* ``risky``       changes existing columns (type, nullability), only with explicit opt-in;
* ``destructive`` drops something the model does not have; reported, never applied.

Every operation is checked against the connected account's privileges, its SQL
is shown before anything runs, and the selected operations are applied in one
transaction (PostgreSQL DDL is transactional, so a failure leaves no change).
"""

import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from alembic.autogenerate import produce_migrations
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.operations import ops as alembic_ops
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - registers every table on the metadata
from app.config import get_settings
from app.db import Base
from app.models import DbConnection
from app.services import secrets

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
PASSWORD_ENV_PATTERN = re.compile(r"^BOP_DBPASS_[A-Z0-9_]{1,50}$")
SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
CURRENT_ID = "current"


class TargetError(ValueError):
    """The connection cannot be used (bad configuration, host not allowed, missing secret)."""


class PlanChanged(RuntimeError):
    pass


@dataclass
class Target:
    key: str
    name: str
    url: URL
    schema: str | None
    sslmode: str | None = None
    builtin: bool = False

    @property
    def dialect(self) -> str:
        return self.url.get_backend_name()

    @property
    def fingerprint(self) -> str:
        return f"{self.dialect}://{self.url.host or ''}:{self.url.port or ''}/{self.url.database or ''}#{self.schema or ''}"


# ------------------------------------------------------------------ targets
def head_revision() -> str | None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(cfg).get_current_head()


def host_allowed(host: str) -> bool:
    settings = get_settings()
    patterns = settings.db_allowed_host_patterns
    if not patterns:
        return settings.app_env.lower() != "production"
    return any(fnmatch(host.lower(), pattern) for pattern in patterns)


def current_target() -> Target:
    url = make_url(get_settings().database_url)
    return Target(key=CURRENT_ID, name="Current application database", url=url, schema=None, builtin=True)


def resolve_password(conn: DbConnection) -> str | None:
    if conn.password_env:
        if not PASSWORD_ENV_PATTERN.match(conn.password_env):
            raise TargetError("Password environment variables must be named BOP_DBPASS_<NAME>.")
        value = os.environ.get(conn.password_env)
        if value is None:
            raise TargetError(f"Environment variable {conn.password_env} is not set on the server.")
        return value
    if conn.password_encrypted:
        try:
            return secrets.decrypt(conn.password_encrypted)
        except ValueError as exc:
            raise TargetError(str(exc)) from exc
    return None


def saved_target(conn: DbConnection, password: str | None = None) -> Target:
    if conn.engine != "postgresql":
        raise TargetError(f"Engine {conn.engine} is not supported.")
    if not host_allowed(conn.host):
        raise TargetError(f"Host {conn.host} is not in DB_CONNECTION_ALLOWED_HOSTS.")
    if not IDENTIFIER.match(conn.schema_name or ""):
        raise TargetError("Invalid schema name.")
    url = URL.create(
        "postgresql+psycopg",
        username=conn.username,
        password=password if password is not None else resolve_password(conn),
        host=conn.host,
        port=conn.port,
        database=conn.database,
    )
    return Target(key=conn.id, name=conn.name, url=url, schema=conn.schema_name, sslmode=conn.sslmode)


def describe_target(t: Target) -> dict:
    return {
        "engine": t.dialect,
        "host": t.url.host,
        "port": t.url.port,
        "database": t.url.database,
        "username": t.url.username,
        "schema": t.schema or ("public" if t.dialect == "postgresql" else None),
    }


def _engine(t: Target) -> Engine:
    connect_args: dict = {}
    if t.dialect == "postgresql":
        connect_args = {"connect_timeout": 5, "application_name": "bop-evolve-config"}
        if t.sslmode:
            connect_args["sslmode"] = t.sslmode
        if t.schema:
            connect_args["options"] = f"-c search_path={t.schema}"
    elif t.dialect == "sqlite":
        connect_args = {"check_same_thread": False}
    return create_engine(t.url, poolclass=NullPool, connect_args=connect_args)


def clean_error(exc: Exception) -> str:
    message = str(getattr(exc, "orig", None) or exc)
    lines = [line.strip() for line in message.splitlines() if line.strip() and not line.startswith("(Background")]
    return " ".join(lines[:3])[:400] or exc.__class__.__name__


# --------------------------------------------------------------- privileges
def _privileges(conn: Connection, t: Target) -> dict:
    if t.dialect != "postgresql":
        return {"supported": False}
    row = (
        conn.execute(
            text(
                """
            SELECT current_user AS user_name,
                   current_database() AS database,
                   current_schema() AS schema,
                   current_setting('server_version') AS version,
                   current_setting('transaction_read_only') = 'on' AS read_only,
                   COALESCE((SELECT rolsuper FROM pg_roles WHERE rolname = current_user), false) AS superuser,
                   has_database_privilege(current_database(), 'CREATE') AS can_create_schema,
                   CASE WHEN current_schema() IS NULL THEN false
                        ELSE has_schema_privilege(current_schema(), 'CREATE') END AS can_create_tables,
                   COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false) AS ssl
            """
            )
        )
        .mappings()
        .one()
    )
    tables = conn.execute(
        text(
            """
            SELECT c.relname AS name, pg_has_role(c.relowner, 'MEMBER') AS owned
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')
            """
        )
    ).all()
    return {
        "supported": True,
        "user": row["user_name"],
        "database": row["database"],
        "schema": row["schema"],
        "server_version": row["version"],
        "read_only": bool(row["read_only"]),
        "superuser": bool(row["superuser"]),
        "can_create_schema": bool(row["can_create_schema"]),
        "can_create_tables": bool(row["can_create_tables"]),
        "ssl": bool(row["ssl"]),
        "owned_tables": sorted(name for name, owned in tables if owned),
        "not_owned_tables": sorted(name for name, owned in tables if not owned),
    }


def test_connection(t: Target) -> dict:
    engine = _engine(t)
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            latency = round((time.perf_counter() - started) * 1000, 1)
            privileges = _privileges(conn, t)
            if t.dialect == "postgresql" and privileges["schema"] is None:
                return {
                    "ok": False,
                    "latency_ms": latency,
                    "error": f"Schema {t.schema or 'public'} does not exist or is not on the search path.",
                    "privileges": privileges,
                }
        return {"ok": True, "latency_ms": latency, "privileges": privileges}
    except SQLAlchemyError as exc:
        return {"ok": False, "error": clean_error(exc)}
    finally:
        engine.dispose()


# ------------------------------------------------------------------ analysis
@dataclass
class Change:
    id: str
    category: str  # safe | risky | destructive
    kind: str
    table: str | None
    column: str | None
    description: str
    sql: str
    allowed: bool
    reason: str | None
    op: alembic_ops.MigrateOperation = field(repr=False)

    def public(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "kind": self.kind,
            "table": self.table,
            "column": self.column,
            "description": self.description,
            "sql": self.sql,
            "allowed": self.allowed,
            "reason": self.reason,
        }


def _flatten(upgrade_ops: alembic_ops.UpgradeOps):
    for op in upgrade_ops.ops:
        if isinstance(op, alembic_ops.ModifyTableOps):
            for sub in op.ops:
                yield op.table_name, sub
        else:
            yield getattr(op, "table_name", None) or getattr(op, "source_table", None), op


def _render_sql(op: alembic_ops.MigrateOperation, dialect: str) -> str:
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect, opts={"as_sql": True, "output_buffer": buffer, "literal_binds": True}
    )
    Operations(context).invoke(op)
    return buffer.getvalue().strip()


def _classify(op, table: str | None, table_has_rows) -> tuple[str, str, str | None, str, str | None]:
    """Return (category, kind, column, description, blocking_reason)."""
    if isinstance(op, alembic_ops.CreateTableOp):
        return "safe", "missing_table", None, f"Create table {table}", None
    if isinstance(op, alembic_ops.DropTableOp):
        return "destructive", "extra_table", None, f"Table {table} is not part of BOP Evolve (left untouched)", None
    if isinstance(op, alembic_ops.AddColumnOp):
        col = op.column
        description = f"Add column {table}.{col.name} {col.type}{'' if col.nullable else ' NOT NULL'}"
        if not col.nullable and col.server_default is None and table_has_rows(table):
            return (
                "risky",
                "missing_column",
                col.name,
                description,
                "NOT NULL column without a default on a table that has rows: backfill or add a default first.",
            )
        return "safe", "missing_column", col.name, description, None
    if isinstance(op, alembic_ops.DropColumnOp):
        return (
            "destructive",
            "extra_column",
            op.column_name,
            f"Column {table}.{op.column_name} is not in the model (left untouched)",
            None,
        )
    if isinstance(op, alembic_ops.AlterColumnOp):
        parts = []
        if op.modify_type is not None:
            parts.append(f"type {op.existing_type} -> {op.modify_type}")
        if op.modify_nullable is not None:
            parts.append("set NOT NULL" if op.modify_nullable is False else "drop NOT NULL")
        if op.modify_server_default is not False:
            parts.append("change server default")
        return "risky", "column_differs", op.column_name, f"Alter {table}.{op.column_name}: {', '.join(parts)}", None
    if isinstance(op, alembic_ops.CreateIndexOp):
        return "safe", "missing_index", None, f"Create index {op.index_name} on {table}", None
    if isinstance(op, alembic_ops.DropIndexOp):
        return "destructive", "extra_index", None, f"Index {op.index_name} on {table} is not in the model", None
    if isinstance(
        op,
        alembic_ops.CreateUniqueConstraintOp | alembic_ops.CreateForeignKeyOp | alembic_ops.CreateCheckConstraintOp,
    ):
        return "safe", "missing_constraint", None, f"Add constraint {op.constraint_name} on {table}", None
    if isinstance(op, alembic_ops.DropConstraintOp):
        return (
            "destructive",
            "extra_constraint",
            None,
            f"Constraint {op.constraint_name} on {table} is not in the model",
            None,
        )
    return "risky", "other", None, op.__class__.__name__, None


def _permission(
    op, table: str | None, category: str, new_tables: set[str], privileges: dict
) -> tuple[bool, str | None]:
    if category == "destructive":
        return False, "Destructive changes are never applied automatically."
    if not privileges.get("supported"):
        return True, None
    user = privileges["user"]
    if privileges["read_only"]:
        return False, "The connection is read-only (replica or read-only transaction)."
    if privileges["superuser"]:
        return True, None
    if isinstance(op, alembic_ops.CreateTableOp) or table in new_tables:
        if privileges["can_create_tables"]:
            return True, None
        return False, f"User {user} cannot create tables in schema {privileges['schema']}."
    if table in privileges["owned_tables"]:
        return True, None
    return False, f"User {user} does not own table {table}, so it cannot alter it."


def _probe(conn: Connection, fn, default):
    """Run a read that may lack privileges inside a savepoint so a failure cannot abort the check."""
    try:
        with conn.begin_nested():
            return fn()
    except SQLAlchemyError:
        return default


@dataclass
class Analysis:
    result: dict
    changes: list[Change]


def _analyse(conn: Connection, t: Target) -> Analysis:
    privileges = _privileges(conn, t)
    if t.dialect == "postgresql" and privileges["schema"] is None:
        raise TargetError(f"Schema {t.schema or 'public'} does not exist or is not on the search path.")
    context = MigrationContext.configure(conn, opts={"compare_type": True, "target_metadata": Base.metadata})
    unreadable = object()
    current_revision = _probe(conn, context.get_current_revision, unreadable)
    revision_readable = current_revision is not unreadable
    if not revision_readable:
        current_revision = None
    script = produce_migrations(context, Base.metadata)
    present = set(inspect(conn).get_table_names())
    quote = conn.dialect.identifier_preparer.quote

    row_cache: dict[str, bool] = {}

    def table_has_rows(table: str) -> bool:
        if table not in row_cache:
            # Unknown (no SELECT privilege) is treated as "has rows", the conservative choice.
            row_cache[table] = bool(
                _probe(conn, lambda: conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {quote(table)})")).scalar(), True)
            )
        return row_cache[table]

    flat = list(_flatten(script.upgrade_ops))
    new_tables = {table for table, op in flat if isinstance(op, alembic_ops.CreateTableOp)}
    changes: list[Change] = []
    for index, (table, op) in enumerate(flat, start=1):
        category, kind, column, description, blocker = _classify(op, table, table_has_rows)
        allowed, reason = _permission(op, table, category, new_tables, privileges)
        if blocker:
            allowed, reason = False, blocker
        changes.append(
            Change(
                id=f"op-{index}",
                category=category,
                kind=kind,
                table=table,
                column=column,
                description=description,
                sql=_render_sql(op, conn.dialect.name),
                allowed=allowed,
                reason=reason,
                op=op,
            )
        )

    expected = sorted(Base.metadata.tables)
    issues_by_table: dict[str, list[dict]] = {name: [] for name in expected}
    extra_tables = []
    for change in changes:
        if change.kind == "extra_table":
            extra_tables.append(change.table)
        elif change.table in issues_by_table and change.kind != "missing_table":
            issues_by_table[change.table].append(
                {
                    "kind": change.kind,
                    "column": change.column,
                    "description": change.description,
                    "category": change.category,
                }
            )
    tables = []
    for name in expected:
        if name in new_tables:
            status = "missing"
        elif issues_by_table[name]:
            status = "differs"
        else:
            status = "ok"
        tables.append({"name": name, "status": status, "issues": issues_by_table[name]})

    head = head_revision()
    counts = {c: sum(1 for ch in changes if ch.category == c) for c in ("safe", "risky", "destructive")}
    pending = counts["safe"] + counts["risky"]
    if len(new_tables) == len(expected) and not (present & set(expected)):
        status = "empty"
    elif pending:
        status = "invalid"
    else:
        status = "valid"
    warnings = []
    if not revision_readable:
        warnings.append("revision_unreadable")
    elif current_revision is None and status == "valid":
        warnings.append("not_stamped")
    elif current_revision not in (None, head):
        warnings.append("unknown_revision")
    if counts["destructive"]:
        warnings.append("extra_objects")

    plan_hash = hashlib.sha256(
        json.dumps({"target": t.fingerprint, "ops": [[c.category, c.sql] for c in changes]}).encode()
    ).hexdigest()
    result = {
        "status": status,
        "revision": {"current": current_revision, "head": head},
        "summary": {
            "expected_tables": len(expected),
            "present_tables": len(present & set(expected)),
            "missing_tables": len(new_tables),
            "differing_tables": sum(1 for t_ in tables if t_["status"] == "differs"),
            "extra_tables": len(extra_tables),
            "changes": counts,
        },
        "tables": tables,
        "extra_tables": sorted(extra_tables),
        "plan": [c.public() for c in changes],
        "plan_hash": plan_hash,
        "privileges": privileges,
        "warnings": warnings,
    }
    return Analysis(result=result, changes=changes)


def check_schema(t: Target) -> dict:
    engine = _engine(t)
    try:
        with engine.connect() as conn:
            return _analyse(conn, t).result
    except TargetError as exc:
        return {"status": "error", "error": str(exc)}
    except SQLAlchemyError as exc:
        return {"status": "error", "error": clean_error(exc)}
    finally:
        engine.dispose()


def needs_stamp(result: dict) -> bool:
    """Tables match but no revision is recorded (e.g. created by hand): record the head revision."""
    privileges = result.get("privileges", {})
    return (
        result.get("status") == "valid"
        and result["revision"]["current"] is None
        and "revision_unreadable" not in result.get("warnings", [])
        and not privileges.get("read_only", False)
    )


def _stamp(conn: Connection, revision: str) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": revision})


def apply_changes(t: Target, plan_hash: str, include_risky: bool) -> dict:
    """Re-analyse, confirm the plan is unchanged, then apply selected changes in one transaction."""
    engine = _engine(t)
    try:
        with engine.connect() as conn:
            analysis = _analyse(conn, t)
        if analysis.result["plan_hash"] != plan_hash:
            raise PlanChanged("The database changed since the last check. Run the schema check again.")

        selected = [c for c in analysis.changes if c.category == "safe" or (include_risky and c.category == "risky")]
        blocked = [c for c in selected if not c.allowed]
        if blocked:
            raise TargetError(
                "Some selected changes cannot be applied: " + "; ".join(c.reason or c.id for c in blocked)
            )
        if not selected:
            if not needs_stamp(analysis.result):
                raise TargetError("There are no changes to apply.")
            head = analysis.result["revision"]["head"]
            with engine.begin() as conn:
                _stamp(conn, head)
            with engine.connect() as conn:
                after = _analyse(conn, t)
            return {"applied": [], "stamped_revision": head, "check": after.result}

        applied = []
        with engine.begin() as conn:
            if t.dialect == "postgresql":
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(text("SET LOCAL statement_timeout = '120s'"))
            operations = Operations(MigrationContext.configure(conn))
            for change in selected:
                try:
                    operations.invoke(change.op)
                except SQLAlchemyError as exc:
                    raise TargetError(f"{change.id} ({change.description}) failed: {clean_error(exc)}") from exc
                applied.append({"id": change.id, "description": change.description, "sql": change.sql})

        with engine.connect() as conn:
            after = _analyse(conn, t)
        stamped = None
        remaining = after.result["summary"]["changes"]
        head = after.result["revision"]["head"]
        if remaining["safe"] + remaining["risky"] == 0 and head and after.result["revision"]["current"] != head:
            with engine.begin() as conn:
                _stamp(conn, head)
            stamped = head
            with engine.connect() as conn:
                after = _analyse(conn, t)
        return {"applied": applied, "stamped_revision": stamped, "check": after.result}
    except SQLAlchemyError as exc:
        raise TargetError(clean_error(exc)) from exc
    finally:
        engine.dispose()
