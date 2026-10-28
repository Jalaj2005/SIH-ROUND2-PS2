import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Fields a client must never set directly: they are owned by the workflow engine.
PROTECTED_FIELDS = frozenset(
    {"status", "current_stage_id", "current_stage", "to_stage", "from_stage", "workflow_template_id",
     "assigned_to", "submitted_at", "institution_id_override"}
)
_PROTECTED_MSG = (
    "Status, stage, template and assignment cannot be set directly; they change only through "
    "POST /applications/{id}/transitions."
)


def _reject_protected(values: Any, allowed: frozenset[str] = frozenset()) -> Any:
    if isinstance(values, dict):
        bad = sorted((set(values) & PROTECTED_FIELDS) - allowed)
        if bad:
            raise ValueError(f"{_PROTECTED_MSG} (offending field: {', '.join(bad)})")
    return values


class StageRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage_code: str
    display_name: str
    sequence: int
    default_sla_hours: int | None = None


class UserRefOut(BaseModel):
    id: str
    name: str
    role: str | None = None


class ApplicationOut(BaseModel):
    id: str
    application_number: str
    institution_id: str
    institution_name: str | None = None
    category: str
    workflow_template_id: str
    workflow_template_name: str | None = None
    status: str
    current_stage: StageRefOut | None = None
    responsible_roles: list[str] = []          # the queue for the current stage
    assigned_to: str | None = None
    assigned_to_name: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    stage_entered_at: datetime | None = None
    stage_due_at: datetime | None = None       # stage_entered_at + default_sla_hours (configurable demo SLA)


class DeficiencyOut(BaseModel):
    history_id: str
    reason: str | None
    returned_at: datetime
    returned_by: UserRefOut | None = None
    checklist_code: str | None = None


class ApplicationDetailOut(ApplicationOut):
    open_deficiency: DeficiencyOut | None = None  # set only while status == RETURNED_FOR_DEFICIENCY


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=100, examples=["NEW_INSTITUTION"])
    submit: bool = Field(False, description="true = create and submit in one call; false = save as DRAFT")
    institution_id: str | None = Field(None, description="Optional; must equal the caller's own institution")

    @model_validator(mode="before")
    @classmethod
    def _no_protected(cls, values):
        return _reject_protected(values)

    @field_validator("category")
    @classmethod
    def _norm_category(cls, v: str) -> str:
        return v.strip().upper()


class ApplicationUpdate(BaseModel):
    """Editable fields only. Status/stage/template/assignment are deliberately not accepted."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(None, min_length=1, max_length=100, description="Only while DRAFT")

    @model_validator(mode="before")
    @classmethod
    def _no_protected(cls, values):
        return _reject_protected(values)

    @field_validator("category")
    @classmethod
    def _norm_category(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=64, examples=["RETURN_FOR_DEFICIENCY"])
    reason: str | None = Field(None, max_length=2000)
    metadata: dict[str, Any] | None = Field(None, examples=[{"checklist_code": "LEASE_SIGNATURE"}])

    @model_validator(mode="before")
    @classmethod
    def _no_protected(cls, values):
        return _reject_protected(values)

    @field_validator("action", mode="before")
    @classmethod
    def _norm_action(cls, v):
        # trim first so a whitespace-only action fails min_length with a 422 instead of reaching the engine
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("metadata")
    @classmethod
    def _limit_metadata(cls, v):
        if v is not None and len(json.dumps(v, default=str)) > 4000:
            raise ValueError("metadata is too large (max 4000 characters serialised)")
        return v
