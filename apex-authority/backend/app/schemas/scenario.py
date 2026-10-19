"""Canonical Scenario schema (spec 6.1) + model-facing generation schema + request/validation models.

`Scenario` is the shared contract. `GeneratedScenario` is what Gemini is asked to produce: it has no
id/status/schema_version, so the model can never choose those. The server maps it to `Scenario`.
"""
from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
ROLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class Domain(str, Enum):
    land = "land"
    air = "air"
    cyber = "cyber"
    electronic_warfare = "electronic_warfare"
    joint_operations = "joint_operations"
    general = "general"


class Difficulty(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class ScenarioStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    archived = "archived"


class FailureType(str, Enum):
    delay = "delay"
    drop = "drop"
    conflicting_report = "conflicting_report"
    incomplete_report = "incomplete_report"


# ---------------------------------------------------------------- canonical scenario
class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str
    display_name: str
    permissions: list[str]
    briefing: str


class InitialReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    title: str
    content: str
    visible_to_roles: list[str]
    source_label: str


class ScenarioEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_key: str
    offset_seconds: int
    event_type: str
    config: dict[str, Any]
    description: str


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    label: str


class EvaluationCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    description: str
    weight: float
    acceptable_option_ids: list[str]
    scoring_notes: str


class DecisionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_key: str
    offset_seconds: int
    prompt: str
    visible_to_roles: list[str]
    options: list[DecisionOption]
    rationale_required: bool
    evaluation_criteria: list[EvaluationCriterion]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    title: str
    description: str
    domain: Domain
    learning_objectives: list[str]
    difficulty: Difficulty
    duration_minutes: int
    roles: list[Role]
    initial_reports: list[InitialReport]
    events: list[ScenarioEvent]
    decision_points: list[DecisionPoint]
    instructor_notes: list[str]
    status: ScenarioStatus
    schema_version: str = SCHEMA_VERSION


# ---------------------------------------------------------------- model-facing schema (no defaults, no id/status)
class GenEventConfig(BaseModel):
    failure_type: FailureType
    duration_seconds: int
    target_roles: list[str]
    target_channel: str


class GenEvent(BaseModel):
    event_key: str
    offset_seconds: int
    event_type: str  # MVP: "communication_failure"
    config: GenEventConfig
    description: str


class GeneratedScenario(BaseModel):
    title: str
    description: str
    domain: Domain
    learning_objectives: list[str]
    difficulty: Difficulty
    duration_minutes: int
    roles: list[Role]
    initial_reports: list[InitialReport]
    events: list[GenEvent]
    decision_points: list[DecisionPoint]
    instructor_notes: list[str]


# ---------------------------------------------------------------- API models
class ValidationIssue(BaseModel):
    field: str
    issue: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


def _clean_list(values: list[str], max_len: int, name: str) -> list[str]:
    out = []
    for v in values:
        v = v.strip()
        if not v:
            raise ValueError(f"{name} entries must not be empty")
        if len(v) > max_len:
            raise ValueError(f"{name} entries must be at most {max_len} characters")
        out.append(v)
    return out


class ScenarioDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: Domain
    learning_objectives: list[str] = Field(min_length=1, max_length=5)
    difficulty: Difficulty
    duration_minutes: int = Field(ge=5, le=120)
    role_count: int = Field(ge=2, le=8)
    role_ids: list[str] = Field(min_length=2, max_length=8)
    communication_failures: list[FailureType] = Field(min_length=1, max_length=4)
    constraints: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("learning_objectives")
    @classmethod
    def _objectives(cls, v): return _clean_list(v, 200, "learning_objectives")

    @field_validator("constraints")
    @classmethod
    def _constraints(cls, v): return _clean_list(v, 300, "constraints")

    @field_validator("role_ids")
    @classmethod
    def _role_ids(cls, v):
        for r in v:
            if not ROLE_ID_PATTERN.match(r):
                raise ValueError("role_ids must match ^[a-z][a-z0-9_]{1,31}$")
        if len(set(v)) != len(v):
            raise ValueError("role_ids must be unique")
        return v

    @model_validator(mode="after")
    def _count_matches(self):
        if self.role_count != len(self.role_ids):
            raise ValueError("role_count must equal len(role_ids)")
        return self


class ScenarioReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str = Field(min_length=3, max_length=2000)


class ScenarioDraftResponse(BaseModel):
    draft_id: uuid.UUID
    version: int
    parent_draft_id: uuid.UUID | None
    scenario: Scenario
    validation: ValidationResult
    status: ScenarioStatus
    prompt_version: str
    model_provider: str
    model_name: str
    warnings: list[ValidationIssue] = Field(default_factory=list)
    created_at: str
