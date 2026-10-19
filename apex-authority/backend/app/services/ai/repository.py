"""AI artefact store.

DEFERRED PERSISTENCE: Module 1 owns db/models.py and Alembic. Until that exists this is an in-memory
implementation behind a narrow interface. Replace `InMemoryAIStore` with a SQLAlchemy-backed class that
has the same methods (tables: ai_scenario_drafts, ai_aar_reports + ai_aar_versions) once the shared DB lands.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.aar import AARReport
from app.schemas.scenario import Scenario, ValidationResult, ValidationIssue


@dataclass
class DraftRecord:
    draft_id: uuid.UUID
    version: int
    parent_draft_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime
    request: dict[str, Any]
    scenario: Scenario
    validation: ValidationResult
    prompt_version: str
    model_provider: str
    model_name: str
    warnings: list[ValidationIssue] = field(default_factory=list)
    attempts: int = 1


@dataclass
class AARRecord:
    report: AARReport
    created_by: uuid.UUID
    allowed_refs: list[str]
    metrics_snapshot: dict[str, Any]       # official Module 1 values, shown verbatim in the PDF
    scenario_title: str
    objectives: list[str]
    session_window: tuple[datetime | None, datetime | None]
    warnings: list[str] = field(default_factory=list)
    versions: list[dict[str, Any]] = field(default_factory=list)  # [{version, source, at, by, report}]


class InMemoryAIStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._drafts: dict[uuid.UUID, DraftRecord] = {}
        self._aars: dict[uuid.UUID, AARRecord] = {}

    def save_draft(self, rec: DraftRecord) -> None:
        with self._lock:
            self._drafts[rec.draft_id] = rec

    def get_draft(self, draft_id: uuid.UUID) -> DraftRecord | None:
        with self._lock:
            return self._drafts.get(draft_id)

    def save_aar(self, rec: AARRecord) -> None:
        with self._lock:
            self._aars[rec.report.id] = rec

    def get_aar(self, aar_id: uuid.UUID) -> AARRecord | None:
        with self._lock:
            return self._aars.get(aar_id)
