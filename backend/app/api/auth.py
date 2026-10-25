from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal, load_grants
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import AuthSession, EmployeeProfile, Role, User, UserRole
from app.services import audit
from app.services.rbac import permissions_for
from app.services.security import issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def principal_payload(db: Session, user: User, grants, employee_id: str | None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "display_name_ar": user.display_name_ar,
        "locale": user.locale,
        "employee_id": employee_id,
        "roles": [{"code": g.role_code, "scope_type": g.scope_type, "scope_id": g.scope_id} for g in grants],
        "permissions": sorted(permissions_for(grants)),
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    if settings.auth_mode != "mock":
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Use the configured SSO/OIDC provider to sign in")
    user = db.scalar(select(User).where(User.username == body.username))
    request_id = getattr(request.state, "request_id", None)
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        audit.record(
            db,
            actor_user_id=user.id if user else None,
            action="auth.login",
            resource_type="session",
            request_id=request_id,
            outcome="denied",
            metadata={"username": body.username},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    expires_at = utcnow() + timedelta(minutes=settings.session_ttl_minutes)
    session = AuthSession(user_id=user.id, expires_at=expires_at)
    db.add(session)
    db.flush()
    audit.record(
        db,
        actor_user_id=user.id,
        action="auth.login",
        resource_type="session",
        resource_id=session.id,
        request_id=request_id,
    )
    db.commit()
    grants = load_grants(db, user.id)
    employee_id = db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user.id))
    return {
        "access_token": issue_token(user.id, session.id, expires_at),
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": principal_payload(db, user, grants, employee_id),
    }


@router.post("/logout")
def logout(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    session = db.get(AuthSession, principal.session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="auth.logout",
        resource_type="session",
        resource_id=principal.session_id,
        request_id=principal.request_id,
    )
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return principal_payload(db, principal.user, principal.grants, principal.employee_id)


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)):
    """Lists demo usernames (never passwords) so the login screen can offer them. Demo mode only."""
    settings = get_settings()
    if not settings.demo_mode or settings.auth_mode != "mock":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available")
    rows = db.execute(
        select(User.username, User.display_name, User.display_name_ar, Role.code)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(or_(~User.username.like("lead.%"), User.username == "lead.br-n01-tel"))
        .order_by(Role.code)
    ).all()
    return [{"username": r[0], "display_name": r[1], "display_name_ar": r[2], "role": r[3]} for r in rows]
