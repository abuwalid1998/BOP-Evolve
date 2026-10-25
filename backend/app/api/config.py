"""System configuration: database connections and schema validation, runtime settings, pipelines."""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import DbConnection, Pipeline, SourceSystem
from app.services import audit, dbschema, secrets, settings_store

router = APIRouter(prefix="/api/config", tags=["configuration"])
public_router = APIRouter(prefix="/api/public", tags=["public"])

HOST_PATTERN = r"^[A-Za-z0-9.\-]+$|^\[[0-9A-Fa-f:]+\]$"


def _iso(value):
    return value.isoformat() if value else None


# ------------------------------------------------------------------ public
@public_router.get("/settings")
def public_settings(db: Session = Depends(get_db)):
    """Pre-login settings the UI needs (no secrets)."""
    return {"default_locale": settings_store.get(db, "general.default_locale")}


# -------------------------------------------------------------- environment
@router.get("/environment")
def environment(principal: Principal = Depends(require("config.view"))):
    s = get_settings()
    current = dbschema.current_target()
    patterns = s.db_allowed_host_patterns
    return {
        "app_env": s.app_env,
        "demo_mode": s.demo_mode,
        "auth_mode": s.auth_mode,
        "log_level": s.log_level,
        "worker_tick_seconds": s.worker_tick_seconds,
        "database": dbschema.describe_target(current),
        "alembic_head": dbschema.head_revision(),
        "config_secret_key_configured": secrets.key_is_configured(),
        "db_allowed_hosts": patterns,
        "db_allowed_hosts_mode": "list" if patterns else ("none" if s.app_env.lower() == "production" else "any"),
        "employee_level_simulation_enabled": s.employee_level_simulation_enabled,
        "version": "0.1.0",
    }


# ----------------------------------------------------------------- settings
class SettingsBody(BaseModel):
    values: dict[str, object] = Field(min_length=1, max_length=50)


@router.get("/settings")
def get_app_settings(principal: Principal = Depends(require("config.view")), db: Session = Depends(get_db)):
    return settings_store.describe(db)


@router.put("/settings")
def put_app_settings(
    body: SettingsBody, principal: Principal = Depends(require("config.manage")), db: Session = Depends(get_db)
):
    try:
        changed = settings_store.update(db, body.values, principal.user.id)
    except settings_store.SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": exc.errors}) from exc
    if changed:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="config.settings_update",
            resource_type="settings",
            request_id=principal.request_id,
            metadata={"changes": {k: {"from": old, "to": new} for k, (old, new) in changed.items()}},
        )
    db.commit()
    return {"changed": sorted(changed), **settings_store.describe(db)}


@router.delete("/settings/{key}")
def reset_app_setting(
    key: str, principal: Principal = Depends(require("config.manage")), db: Session = Depends(get_db)
):
    try:
        changed = settings_store.reset(db, key)
    except settings_store.SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": exc.errors}) from exc
    if changed:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="config.settings_reset",
            resource_type="settings",
            resource_id=key,
            request_id=principal.request_id,
            metadata={"changes": {k: {"from": old, "to": new} for k, (old, new) in changed.items()}},
        )
    db.commit()
    return {"changed": sorted(changed), **settings_store.describe(db)}


# ---------------------------------------------------------------- pipelines
@router.get("/pipelines")
def list_pipelines(principal: Principal = Depends(require("config.view")), db: Session = Depends(get_db)):
    rows = db.execute(select(Pipeline, SourceSystem).join(SourceSystem).order_by(Pipeline.code)).all()
    return [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "source": s.name,
            "state": p.state,
            "schedule_seconds": p.schedule_seconds,
            "freshness_sla_minutes": p.freshness_sla_minutes,
            "owner": p.owner,
            "runbook_url": p.runbook_url,
        }
        for p, s in rows
    ]


class PipelinePatch(BaseModel):
    schedule_seconds: int | None = Field(None, ge=30, le=86400)
    freshness_sla_minutes: int | None = Field(None, ge=1, le=10080)
    owner: str | None = Field(None, min_length=2, max_length=120)
    runbook_url: str | None = Field(None, max_length=255, pattern=r"^https?://\S+$")


@router.patch("/pipelines/{pipeline_id}")
def patch_pipeline(
    pipeline_id: str,
    body: PipelinePatch,
    principal: Principal = Depends(require("config.manage")),
    db: Session = Depends(get_db),
):
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    changes = {}
    for field_name, value in body.model_dump(exclude_none=True).items():
        old = getattr(pipeline, field_name)
        if old != value:
            changes[field_name] = {"from": old, "to": value}
            setattr(pipeline, field_name, value)
    if "schedule_seconds" in changes:
        sooner = utcnow() + timedelta(seconds=pipeline.schedule_seconds)
        if pipeline.next_run_at is None or pipeline.next_run_at > sooner:
            pipeline.next_run_at = sooner
    if changes:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="config.pipeline_update",
            resource_type="pipeline",
            resource_id=pipeline.id,
            request_id=principal.request_id,
            metadata=changes,
        )
    db.commit()
    return {"id": pipeline.id, "changed": sorted(changes)}


# ------------------------------------------------------- database connections
class ConnectionBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    engine: Literal["postgresql"] = "postgresql"
    host: str = Field(min_length=1, max_length=255, pattern=HOST_PATTERN)
    port: int = Field(5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_\-]+$")
    username: str = Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_.@\-]+$")
    password: str | None = Field(None, max_length=256)
    clear_password: bool = False
    password_env: str | None = Field(None, max_length=64)
    sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    schema_name: str = Field("public", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _password_source(self):
        if self.password_env:
            if not dbschema.PASSWORD_ENV_PATTERN.match(self.password_env):
                raise ValueError("password_env must be named BOP_DBPASS_<NAME> (A-Z, 0-9, _)")
            if self.password:
                raise ValueError("Use either a password or a password environment variable, not both")
        return self


def _connection_dict(c: DbConnection) -> dict:
    return {
        "id": c.id,
        "builtin": False,
        "name": c.name,
        "engine": c.engine,
        "host": c.host,
        "port": c.port,
        "database": c.database,
        "username": c.username,
        "schema": c.schema_name,
        "sslmode": c.sslmode,
        "notes": c.notes,
        "password_source": "env" if c.password_env else ("stored" if c.password_encrypted else "none"),
        "password_env": c.password_env,
        "host_allowed": dbschema.host_allowed(c.host),
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
        "last_test_at": _iso(c.last_test_at),
        "last_test_ok": c.last_test_ok,
        "last_check_at": _iso(c.last_check_at),
        "last_check_status": c.last_check_status,
        "last_check_summary": c.last_check_summary,
    }


def _current_dict() -> dict:
    t = dbschema.current_target()
    return {
        "id": dbschema.CURRENT_ID,
        "builtin": True,
        "name": t.name,
        **dbschema.describe_target(t),
        "password_source": "environment",
        "host_allowed": True,
    }


def _get_connection(db: Session, connection_id: str) -> DbConnection:
    conn = db.get(DbConnection, connection_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return conn


def _target(db: Session, connection_id: str) -> tuple[dbschema.Target, DbConnection | None]:
    if connection_id == dbschema.CURRENT_ID:
        return dbschema.current_target(), None
    conn = _get_connection(db, connection_id)
    try:
        return dbschema.saved_target(conn), conn
    except dbschema.TargetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _apply_body(conn: DbConnection, body: ConnectionBody, actor_id: str) -> None:
    conn.name = body.name.strip()
    conn.engine = body.engine
    conn.host = body.host.strip()
    conn.port = body.port
    conn.database = body.database
    conn.username = body.username
    conn.sslmode = body.sslmode
    conn.schema_name = body.schema_name
    conn.notes = body.notes
    if body.password_env:
        conn.password_env = body.password_env
        conn.password_encrypted = None
    else:
        conn.password_env = None
        if body.clear_password:
            conn.password_encrypted = None
        elif body.password:
            conn.password_encrypted = secrets.encrypt(body.password)
    conn.updated_at = utcnow()
    conn.updated_by = actor_id


@router.get("/db-connections")
def list_connections(principal: Principal = Depends(require("config.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(DbConnection).order_by(DbConnection.name)).all()
    return [_current_dict(), *[_connection_dict(c) for c in rows]]


@router.post("/db-connections", status_code=201)
def create_connection(
    body: ConnectionBody, principal: Principal = Depends(require("config.manage")), db: Session = Depends(get_db)
):
    if db.scalar(select(DbConnection).where(DbConnection.name == body.name.strip())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection with this name already exists")
    conn = DbConnection(created_by=principal.user.id)
    _apply_body(conn, body, principal.user.id)
    db.add(conn)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_connection_create",
        resource_type="db_connection",
        resource_id=conn.id,
        request_id=principal.request_id,
        metadata={
            "host": conn.host,
            "database": conn.database,
            "password_source": _connection_dict(conn)["password_source"],
        },
    )
    db.commit()
    return _connection_dict(conn)


@router.put("/db-connections/{connection_id}")
def update_connection(
    connection_id: str,
    body: ConnectionBody,
    principal: Principal = Depends(require("config.manage")),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, connection_id)
    clash = db.scalar(select(DbConnection).where(DbConnection.name == body.name.strip(), DbConnection.id != conn.id))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection with this name already exists")
    _apply_body(conn, body, principal.user.id)
    conn.last_check_status = None  # any edit invalidates the previous check
    conn.last_check_summary = None
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_connection_update",
        resource_type="db_connection",
        resource_id=conn.id,
        request_id=principal.request_id,
        metadata={
            "host": conn.host,
            "database": conn.database,
            "password_changed": bool(body.password or body.clear_password),
        },
    )
    db.commit()
    return _connection_dict(conn)


@router.delete("/db-connections/{connection_id}")
def delete_connection(
    connection_id: str, principal: Principal = Depends(require("config.manage")), db: Session = Depends(get_db)
):
    conn = _get_connection(db, connection_id)
    db.delete(conn)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_connection_delete",
        resource_type="db_connection",
        resource_id=connection_id,
        request_id=principal.request_id,
        metadata={"name": conn.name},
    )
    db.commit()
    return {"ok": True}


@router.post("/db-connections/test-draft")
def test_draft(
    body: ConnectionBody, principal: Principal = Depends(require("config.manage")), db: Session = Depends(get_db)
):
    """Test connection details before saving them (the password is not stored)."""
    draft = DbConnection(
        id="draft",
        name=body.name,
        engine=body.engine,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password_env=body.password_env,
        sslmode=body.sslmode,
        schema_name=body.schema_name,
    )
    try:
        target = dbschema.saved_target(draft, password=body.password if not body.password_env else None)
    except dbschema.TargetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    result = dbschema.test_connection(target)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_test",
        resource_type="db_connection",
        resource_id="draft",
        request_id=principal.request_id,
        outcome="success" if result["ok"] else "failure",
        metadata={"host": body.host, "database": body.database},
    )
    db.commit()
    return result


@router.post("/db-connections/{connection_id}/test")
def test_saved(
    connection_id: str, principal: Principal = Depends(require("config.view")), db: Session = Depends(get_db)
):
    target, conn = _target(db, connection_id)
    result = dbschema.test_connection(target)
    if conn is not None:
        conn.last_test_at = utcnow()
        conn.last_test_ok = result["ok"]
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_test",
        resource_type="db_connection",
        resource_id=connection_id,
        request_id=principal.request_id,
        outcome="success" if result["ok"] else "failure",
    )
    db.commit()
    return result


def _can_apply(principal: Principal, result: dict) -> dict:
    blockers = []
    if not principal.has("config.manage"):
        blockers.append("app_permission")
    if result.get("status") == "error":
        blockers.append("check_failed")
    plan = result.get("plan", [])
    applicable = [c for c in plan if c["category"] in ("safe", "risky")]
    if not applicable and not dbschema.needs_stamp(result):
        blockers.append("nothing_to_apply")
    if any(not c["allowed"] for c in applicable if c["category"] == "safe"):
        blockers.append("db_privileges")
    risky = [c for c in plan if c["category"] == "risky"]
    return {
        "can_apply": not blockers,
        "blockers": blockers,
        "can_apply_risky": not blockers and bool(risky) and all(c["allowed"] for c in risky),
        "stamp_only": not applicable and dbschema.needs_stamp(result),
    }


@router.post("/db-connections/{connection_id}/schema-check")
def schema_check(
    connection_id: str, principal: Principal = Depends(require("config.view")), db: Session = Depends(get_db)
):
    target, conn = _target(db, connection_id)
    result = dbschema.check_schema(target)
    summary = {"status": result["status"], **result.get("summary", {}), "revision": result.get("revision")}
    if conn is not None:
        conn.last_check_at = utcnow()
        conn.last_check_status = result["status"]
        conn.last_check_summary = summary
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_schema_check",
        resource_type="db_connection",
        resource_id=connection_id,
        request_id=principal.request_id,
        outcome="failure" if result["status"] == "error" else "success",
        metadata={"status": result["status"], "changes": result.get("summary", {}).get("changes")},
    )
    db.commit()
    return {
        "connection": _current_dict() if conn is None else _connection_dict(conn),
        "checked_at": utcnow().isoformat(),
        **result,
        **_can_apply(principal, result),
    }


class ApplyBody(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)
    include_risky: bool = False
    confirm_database: str = Field(min_length=1, max_length=255)


@router.post("/db-connections/{connection_id}/apply")
def apply_schema(
    connection_id: str,
    body: ApplyBody,
    principal: Principal = Depends(require("config.manage")),
    db: Session = Depends(get_db),
):
    target, conn = _target(db, connection_id)
    if body.confirm_database != (target.url.database or ""):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Type the database name exactly to confirm")
    metadata = {"plan_hash": body.plan_hash, "include_risky": body.include_risky, "database": target.url.database}
    try:
        outcome = dbschema.apply_changes(target, body.plan_hash, body.include_risky)
    except dbschema.PlanChanged as exc:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="config.db_apply",
            resource_type="db_connection",
            resource_id=connection_id,
            request_id=principal.request_id,
            outcome="denied",
            metadata={**metadata, "reason": "plan_changed"},
        )
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except dbschema.TargetError as exc:
        audit.record(
            db,
            actor_user_id=principal.user.id,
            action="config.db_apply",
            resource_type="db_connection",
            resource_id=connection_id,
            request_id=principal.request_id,
            outcome="failure",
            metadata={**metadata, "error": str(exc)[:300]},
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    check = outcome["check"]
    if conn is not None:
        conn.last_check_at = utcnow()
        conn.last_check_status = check["status"]
        conn.last_check_summary = {
            "status": check["status"],
            **check.get("summary", {}),
            "revision": check.get("revision"),
        }
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="config.db_apply",
        resource_type="db_connection",
        resource_id=connection_id,
        request_id=principal.request_id,
        metadata={**metadata, "applied": len(outcome["applied"]), "stamped_revision": outcome["stamped_revision"]},
    )
    db.commit()
    return {
        "applied": outcome["applied"],
        "stamped_revision": outcome["stamped_revision"],
        "check": {
            "connection": _current_dict() if conn is None else _connection_dict(conn),
            "checked_at": utcnow().isoformat(),
            **check,
            **_can_apply(principal, check),
        },
    }
