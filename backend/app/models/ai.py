from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, new_id, utcnow


class AIGeneration(Base):
    """One call to the generative assistant: what was asked (as a hash), what came back and who asked.

    Doubles as a cache: an identical request (same task, model, prompt version, language and
    input) reuses the stored output instead of calling the provider again. Inputs are
    pseudonymised before they are hashed or sent; the stored output never contains the key.
    """

    __tablename__ = "ai_generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("AIG"))
    feature: Mapped[str] = mapped_column(String(40))
    task: Mapped[str] = mapped_column(String(40))
    prompt_version: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(8))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    output: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    __table_args__ = (CheckConstraint("status IN ('ok','error')", name="status"),)
