from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, new_id, utcnow

ORG_UNIT_TYPES = ("bank", "department", "region", "branch", "section")
SCOPE_TYPES = ("global", "department", "region", "branch", "section", "self")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("USR"))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    display_name_ar: Mapped[str | None] = mapped_column(String(120))
    # Prototype-only local credential. Production authentication uses SSO/OIDC.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="status"),)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ROL"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500))


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("URL"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    scope_id: Mapped[str | None] = mapped_column(String(32))
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope_type", "scope_id", name="uq_user_roles_assignment"),
        CheckConstraint(
            "scope_type IN ('global','department','region','branch','section','self')", name="scope_type"
        ),
    )


class AuthSession(Base):
    """Server-side session record so that logout and expiry are enforced."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("SES"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ORG"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("org_units.id"), index=True)
    unit_type: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("unit_type IN ('bank','department','region','branch','section')", name="unit_type"),
    )


class EmployeeProfile(Base):
    """Restricted employee mapping. Demo profiles use pseudonymous labels only."""

    __tablename__ = "employee_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("EMP"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), unique=True)
    pseudonym: Mapped[str] = mapped_column(String(40), unique=True)
    org_unit_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    role_title: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")

    org_unit: Mapped[OrgUnit] = relationship()
