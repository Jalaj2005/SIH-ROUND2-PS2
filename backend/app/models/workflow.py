from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime
from app.core.errors import AppendOnlyViolation
from app.core.ids import new_id, utcnow


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (UniqueConstraint("category", "version", name="uq_template_category_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wft"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WorkflowStage(Base):
    __tablename__ = "workflow_stages"
    __table_args__ = (UniqueConstraint("template_id", "stage_code", name="uq_stage_template_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("stg"))
    template_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_templates.id"), index=True)
    stage_code: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(200))
    sequence: Mapped[int] = mapped_column(Integer)
    allowed_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WorkflowTransition(Base):
    """Allowed transition map. from_stage/to_stage hold stage_code values scoped to template_id."""

    __tablename__ = "workflow_transitions"
    __table_args__ = (UniqueConstraint("template_id", "from_stage", "action", name="uq_transition_from_action"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wtr"))
    template_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_templates.id"), index=True)
    from_stage: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    to_stage: Mapped[str] = mapped_column(String(64))
    required_role: Mapped[str] = mapped_column(String(40))
    requires_reason: Mapped[bool] = mapped_column(Boolean, default=False)


class Application(Base):
    """Never PATCH status/current_stage_id directly; Module 1's transition endpoint owns those."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("app"))
    application_number: Mapped[str] = mapped_column(String(64), unique=True)
    institution_id: Mapped[str] = mapped_column(String(64), ForeignKey("institutions.id"), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    workflow_template_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_templates.id"))
    status: Mapped[str] = mapped_column(String(40), index=True)
    current_stage_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workflow_stages.id"), nullable=True
    )
    assigned_to: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ApplicationStageHistory(Base):
    """Append-only."""

    __tablename__ = "application_stage_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("hist"))
    application_id: Mapped[str] = mapped_column(String(64), ForeignKey("applications.id"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


def _block(_mapper, _connection, target):
    raise AppendOnlyViolation(f"{type(target).__name__} rows are append-only.")


for _evt in ("before_update", "before_delete"):
    event.listen(ApplicationStageHistory, _evt, _block)
