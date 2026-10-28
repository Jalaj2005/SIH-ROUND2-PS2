from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.ids import utcnow
from app.models.ops import AuditLog


def log_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_id: str | None = None,
    reason: str | None = None,
    before: Any = None,
    after: Any = None,
    request_id: str | None = None,
) -> AuditLog:
    """Stage an audit row on the caller's session. It does NOT commit: the caller commits once, so the
    audit record and the change it describes land in the same transaction."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        timestamp=utcnow(),
        reason=reason,
        before_json=jsonable_encoder(before) if before is not None else None,
        after_json=jsonable_encoder(after) if after is not None else None,
        request_id=request_id,
    )
    db.add(entry)
    return entry
