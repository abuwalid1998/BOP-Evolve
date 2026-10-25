from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow


class AppSetting(Base):
    """Runtime override of a configurable setting. Absent key = built-in default."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class DbConnection(Base):
    """Saved database connection profile. Passwords are encrypted or referenced, never stored in clear."""

    __tablename__ = "db_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("DBC"))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    engine: Mapped[str] = mapped_column(String(20), default="postgresql")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database: Mapped[str] = mapped_column(String(63))
    username: Mapped[str] = mapped_column(String(63))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    password_env: Mapped[str | None] = mapped_column(String(64))
    sslmode: Mapped[str] = mapped_column(String(16), default="prefer")
    schema_name: Mapped[str] = mapped_column(String(63), default="public")
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_check_status: Mapped[str | None] = mapped_column(String(16))
    last_check_summary: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint("engine IN ('postgresql')", name="engine"),
        CheckConstraint("sslmode IN ('disable','allow','prefer','require','verify-ca','verify-full')", name="sslmode"),
    )
