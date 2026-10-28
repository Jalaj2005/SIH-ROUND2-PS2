from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.application import UserRefOut


class AllowedActionOut(BaseModel):
    action: str
    label: str
    to_stage: str
    to_stage_display_name: str | None = None
    requires_reason: bool


class AllowedActionsOut(BaseModel):
    application_id: str
    status: str
    actions: list[AllowedActionOut]


class HistoryEntryOut(BaseModel):
    id: str
    entry_type: str                      # STAGE_TRANSITION | AUDIT_EVENT
    action: str
    from_stage: str | None = None
    to_stage: str | None = None
    reason: str | None = None
    actor: UserRefOut | None = None
    created_at: datetime
    metadata: dict[str, Any] | None = None


class TemplateStageOut(BaseModel):
    stage_code: str
    display_name: str
    sequence: int
    allowed_roles: list[str]
    default_sla_hours: int | None = None


class TemplateTransitionOut(BaseModel):
    from_stage: str
    action: str
    to_stage: str
    required_role: str                   # "SYSTEM" = automatic routing step
    requires_reason: bool


class WorkflowTemplateOut(BaseModel):
    id: str
    name: str
    category: str
    version: int
    is_active: bool
    stages: list[TemplateStageOut]
    transitions: list[TemplateTransitionOut]
