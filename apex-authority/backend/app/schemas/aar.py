"""AAR input (6.3, consumed from Module 1), AAR output (6.4) and the model-facing GeneratedAAR."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class AARStatus(str, Enum):
    draft = "draft"
    reviewed = "reviewed"
    exported = "exported"


class Classification(str, Enum):
    fact = "fact"
    interpretation = "interpretation"
    recommendation = "recommendation"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


# ---------------------------------------------------------------- AAR input (tolerant reader: extra ignored)
class AARScenarioRef(BaseModel):
    scenario_id: uuid.UUID
    title: str
    learning_objectives: list[str]


class AARSessionSummary(BaseModel):
    started_at: datetime | None
    ended_at: datetime | None
    participant_count: int


class AARParticipant(BaseModel):
    user_id: uuid.UUID
    display_name: str
    role_id: str


class AARDecision(BaseModel):
    decision_id: uuid.UUID
    decision_key: str
    role_id: str
    selected_option_id: str
    rationale: str | None = None
    submitted_at: datetime
    available_evidence_refs: list[str] = Field(default_factory=list)
    score: float | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class AAREvent(BaseModel):
    event_id: uuid.UUID
    sequence_no: int
    event_type: str
    occurred_at: datetime
    scenario_offset_seconds: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AARInput(BaseModel):
    session_id: uuid.UUID
    scenario: AARScenarioRef
    session_summary: AARSessionSummary
    participants: list[AARParticipant] = Field(default_factory=list)
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    decisions: list[AARDecision] = Field(default_factory=list)
    events: list[AAREvent] = Field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


# ---------------------------------------------------------------- model-facing + canonical output
class KeyObservation(BaseModel):
    observation: str
    classification: Classification
    evidence_refs: list[str]
    confidence: Confidence


class Finding(BaseModel):
    text: str
    evidence_refs: list[str]


class Recommendation(BaseModel):
    text: str
    related_learning_objective: str


class GeneratedAAR(BaseModel):
    """Exactly what Gemini is asked to return. No scores, timestamps, ids or status."""
    title: str
    executive_summary: str
    key_observations: list[KeyObservation]
    strengths: list[Finding]
    improvement_areas: list[Finding]
    recommendations: list[Recommendation]
    evidence_limitations: list[str]
    follow_up_scenario_brief: str


class AARReport(BaseModel):
    """Canonical AAR output (spec 6.4)."""
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    session_id: uuid.UUID
    status: AARStatus
    title: str
    executive_summary: str
    key_observations: list[KeyObservation]
    strengths: list[Finding]
    improvement_areas: list[Finding]
    recommendations: list[Recommendation]
    evidence_limitations: list[str]
    follow_up_scenario_brief: str
    model_provider: str
    model_name: str
    prompt_version: str
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: uuid.UUID | None = None


class AARCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID
    include_individual_feedback: bool = False
    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class AARCreateResponse(BaseModel):
    aar_id: uuid.UUID
    session_id: uuid.UUID
    status: AARStatus
    report: AARReport
    warnings: list[str] = Field(default_factory=list)
    version_count: int = 1  # additive: number of stored report versions (AI original + edits)


class AARUpdateRequest(BaseModel):
    """Instructor edits. Only narrative fields are editable; provenance/status/ids are not."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=300)
    executive_summary: str | None = Field(default=None, min_length=1, max_length=6000)
    key_observations: list[KeyObservation] | None = None
    strengths: list[Finding] | None = None
    improvement_areas: list[Finding] | None = None
    recommendations: list[Recommendation] | None = None
    evidence_limitations: list[str] | None = None
    follow_up_scenario_brief: str | None = Field(default=None, max_length=4000)
