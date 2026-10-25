"""Administration: users, roles, org units, integrations and audit."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.db import get_db
from app.models import AuditEvent, OrgUnit, Role, SourceSystem, User, UserRole
from app.models.org import SCOPE_TYPES
from app.services import audit
from app.services.rbac import PERMISSIONS, ROLE_CATALOGUE, ROLE_PERMISSIONS
from app.services.scoping import unit_ref

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso(v: datetime | None):
    return v.isoformat() if v else None


@router.get("/users")
def list_users(principal: Principal = Depends(require("admin.view")), db: Session = Depends(get_db)):
    units = {u.id: u for u in db.scalars(select(OrgUnit))}
    roles = {r.id: r for r in db.scalars(select(Role))}
    users = db.scalars(select(User).order_by(User.username)).all()
    grants: dict[str, list] = {}
    for ur in db.scalars(select(UserRole)):
        grants.setdefault(ur.user_id, []).append(
            {
                "id": ur.id,
                "role": roles[ur.role_id].code,
                "scope_type": ur.scope_type,
                "scope": unit_ref(units.get(ur.scope_id)) if ur.scope_id else None,
                "granted_at": _iso(ur.granted_at),
            }
        )
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "display_name_ar": u.display_name_ar,
            "status": u.status,
            "created_at": _iso(u.created_at),
            "grants": grants.get(u.id, []),
        }
        for u in users
    ]


class GrantBody(BaseModel):
    role: str
    scope_type: str
    scope_id: str | None = None


@router.post("/users/{user_id}/roles", status_code=201)
def grant_role(
    user_id: str,
    body: GrantBody,
    principal: Principal = Depends(require("admin.manage")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    role = db.scalar(select(Role).where(Role.code == body.role))
    if user is None or role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User or role not found")
    if body.scope_type not in SCOPE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid scope type")
    if body.scope_type in ("global", "self"):
        body.scope_id = None
    else:
        unit = db.get(OrgUnit, body.scope_id) if body.scope_id else None
        if unit is None or unit.unit_type != body.scope_type:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scope must reference an org unit of that type")
    exists = db.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
            UserRole.scope_type == body.scope_type,
            UserRole.scope_id == body.scope_id,
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Role already granted with this scope")
    grant = UserRole(user_id=user.id, role_id=role.id, scope_type=body.scope_type, scope_id=body.scope_id)
    db.add(grant)
    db.flush()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="admin.role_grant",
        resource_type="user",
        resource_id=user.id,
        request_id=principal.request_id,
        metadata={"role": role.code, "scope_type": body.scope_type, "scope_id": body.scope_id},
    )
    db.commit()
    return {"id": grant.id}


@router.delete("/users/{user_id}/roles/{grant_id}")
def revoke_role(
    user_id: str, grant_id: str, principal: Principal = Depends(require("admin.manage")), db: Session = Depends(get_db)
):
    grant = db.get(UserRole, grant_id)
    if grant is None or grant.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    role = db.get(Role, grant.role_id)
    if user_id == principal.user.id and role.code == "super_admin":
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove your own Super Admin role")
    db.delete(grant)
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="admin.role_revoke",
        resource_type="user",
        resource_id=user_id,
        request_id=principal.request_id,
        metadata={"role": role.code},
    )
    db.commit()
    return {"ok": True}


@router.get("/roles")
def roles(principal: Principal = Depends(require("admin.view"))):
    return {
        "permissions": PERMISSIONS,
        "roles": [
            {"code": code, **spec, "permissions": sorted(ROLE_PERMISSIONS[code])}
            for code, spec in ROLE_CATALOGUE.items()
        ],
        "note": "Proposed mapping — must be validated by HR and organisational owners.",
    }


@router.get("/org-units")
def org_units(
    principal: Principal = Depends(require("admin.view", "insights.view", "cases.view", "simulations.run")),
    db: Session = Depends(get_db),
):
    return [
        {**unit_ref(u), "parent_id": u.parent_id, "active": u.active}
        for u in db.scalars(select(OrgUnit).order_by(OrgUnit.code))
    ]


@router.get("/source-systems")
def source_systems(principal: Principal = Depends(require("admin.view")), db: Session = Depends(get_db)):
    return [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "type": s.system_type,
            "owner": s.owner,
            "enabled": s.enabled,
            "approved_for_use": s.approved_for_use,
        }
        for s in db.scalars(select(SourceSystem).order_by(SourceSystem.code))
    ]


class SourcePatch(BaseModel):
    enabled: bool


@router.patch("/source-systems/{source_id}")
def update_source(
    source_id: str,
    body: SourcePatch,
    principal: Principal = Depends(require("admin.manage")),
    db: Session = Depends(get_db),
):
    source = db.get(SourceSystem, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if body.enabled and not source.approved_for_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "Source has not been approved for use")
    source.enabled = body.enabled
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="admin.source_toggle",
        resource_type="source_system",
        resource_id=source.id,
        request_id=principal.request_id,
        metadata={"enabled": body.enabled},
    )
    db.commit()
    return {"id": source.id, "enabled": source.enabled}


@router.get("/audit-events")
def audit_events(
    action: str | None = None,
    actor: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require("audit.view")),
    db: Session = Depends(get_db),
):
    stmt = select(AuditEvent, User.username).outerjoin(User, User.id == AuditEvent.actor_user_id)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"{action}%"))
    if actor:
        stmt = stmt.where(User.username == actor)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(AuditEvent.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "occurred_at": _iso(e.occurred_at),
                "actor": username,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "outcome": e.outcome,
                "request_id": e.request_id,
                "metadata": e.metadata_redacted,
            }
            for e, username in rows
        ],
    }
