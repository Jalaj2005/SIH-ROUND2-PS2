import uuid
from datetime import datetime, timezone


def new_id(prefix: str) -> str:
    """Consistent string IDs across modules, e.g. app_3f9c1a7e2b10."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_request_id() -> str:
    return new_id("req")


def utcnow() -> datetime:
    """All timestamps are stored as timezone-aware UTC."""
    return datetime.now(timezone.utc)
