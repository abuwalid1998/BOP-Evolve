from sqlalchemy.orm import Session

from app.models import AuditEvent

_REDACTED_KEYS = {"password", "token", "access_token", "secret", "authorization", "response_text", "rationale"}


def _redact(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    clean: dict = {}
    for key, value in metadata.items():
        if key.lower() in _REDACTED_KEYS:
            clean[key] = "[redacted]"
        elif isinstance(value, dict):
            clean[key] = _redact(value)
        else:
            clean[key] = value
    return clean


def record(
    db: Session,
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    request_id: str | None = None,
    outcome: str = "success",
    metadata: dict | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (caller commits)."""
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        outcome=outcome,
        metadata_redacted=_redact(metadata),
    )
    db.add(event)
    return event
