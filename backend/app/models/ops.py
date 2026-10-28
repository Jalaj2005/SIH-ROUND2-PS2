from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, event, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime
from app.core.errors import AppendOnlyViolation
from app.core.ids import new_id, utcnow


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # At most one ACTIVE alert per dedupe_key (retry-safe alert creation).
        Index(
            "uq_notifications_active_dedupe",
            "dedupe_key",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_notifications_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ntf"))
    recipient_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    rule_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (Index("ix_escalations_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("esc"))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    rule_code: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(Integer, default=1)
    escalated_to: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditLog(Base):
    """Append-only (enforced for ORM updates/deletes; also restrict UPDATE/DELETE at DB level in production)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("aud"))
    actor_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkflowRule(Base):
    """Configurable rules/thresholds (the brief's workflow_rules / deadline_policies). Changes must be audited."""

    __tablename__ = "workflow_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rul"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


def _block(_mapper, _connection, target):
    raise AppendOnlyViolation(f"{type(target).__name__} rows are append-only.")


for _evt in ("before_update", "before_delete"):
    event.listen(AuditLog, _evt, _block)
