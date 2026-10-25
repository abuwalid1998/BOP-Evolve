from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.models import AuthSession, EmployeeProfile, Role, User, UserRole
from app.services.rbac import Grant, Scope, permissions_for, resolve_scope
from app.services.security import decode_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    session_id: str
    grants: list[Grant]
    permissions: set[str]
    employee_id: str | None
    request_id: str | None

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def scope(self, db: Session, permission: str) -> Scope:
        return resolve_scope(db, self.grants, permission, self.employee_id)


def load_grants(db: Session, user_id: str) -> list[Grant]:
    rows = db.execute(
        select(Role.code, UserRole.scope_type, UserRole.scope_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    return [Grant(code, scope_type, scope_id) for code, scope_type, scope_id in rows]


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if credentials is None:
        raise unauthorised
    try:
        claims = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise unauthorised from exc

    session = db.get(AuthSession, claims.get("sid"))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or signed out")
    user = db.get(User, claims.get("sub"))
    if user is None or user.status != "active" or user.id != session.user_id:
        raise unauthorised

    grants = load_grants(db, user.id)
    employee_id = db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user.id))
    return Principal(
        user=user,
        session_id=session.id,
        grants=grants,
        permissions=permissions_for(grants),
        employee_id=employee_id,
        request_id=getattr(request.state, "request_id", None),
    )


def require(*permissions: str) -> Callable[..., Principal]:
    """Dependency that requires *any* of the given permissions."""

    def checker(principal: Principal = Depends(get_principal)) -> Principal:
        if not any(principal.has(p) for p in permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this resource")
        return principal

    return checker
