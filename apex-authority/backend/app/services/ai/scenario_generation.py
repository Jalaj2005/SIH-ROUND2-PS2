"""Feature A: AI-assisted scenario drafting. Produces DRAFTS only; approval/activation live in Module 1."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CurrentUser
from app.schemas.scenario import (
    GeneratedScenario, Scenario, ScenarioDraftRequest, ScenarioStatus, SCHEMA_VERSION, ValidationIssue,
)
from app.schemas.scenario_rules import validate_scenario
from app.services.ai.generation import generate_validated
from app.services.ai.prompts import scenario_v1 as prompt
from app.services.ai.provider import LLMProvider
from app.services.ai.repository import DraftRecord, InMemoryAIStore
from app.services.ai.sanitize import clean_obj, clean_text, detect_injection

INJECTION_WARNING = ValidationIssue(
    field="input",
    issue="Input contained instruction-like text. It was treated as data only; review the draft carefully.",
)


def to_canonical(gen: GeneratedScenario, scenario_id: uuid.UUID) -> Scenario:
    """Server-controlled fields (id, status, schema_version) are set here, never taken from the model."""
    data = gen.model_dump(mode="json")
    return Scenario.model_validate({**data, "id": scenario_id, "status": ScenarioStatus.draft.value,
                                    "schema_version": SCHEMA_VERSION})


class ScenarioGenerationService:
    def __init__(self, provider: LLMProvider, store: InMemoryAIStore, settings: Settings, sleep=None):
        self.provider, self.store, self.settings = provider, store, settings
        self._sleep = sleep or time.sleep

    def _run(self, *, request: ScenarioDraftRequest, user: CurrentUser, scenario_id: uuid.UUID, version: int,
             parent: uuid.UUID | None, feedback: str | None, previous: dict | None, extra_flags: list[str]) -> DraftRecord:
        clean_req = clean_obj(request.model_dump(mode="json"))
        flags = detect_injection([clean_req, feedback or ""]) + extra_flags
        validations: dict[str, object] = {}

        def build(errors): return prompt.build_user_prompt(clean_req, feedback=feedback, previous=previous, validation_errors=errors)

        def validate(gen: GeneratedScenario) -> list[ValidationIssue]:
            result = validate_scenario(to_canonical(gen, scenario_id), request)
            validations["last"] = result
            return result.errors

        gen, attempts = generate_validated(
            provider=self.provider, settings=self.settings, system=prompt.SYSTEM, build_prompt=build,
            response_model=GeneratedScenario, validate=validate, sleep=self._sleep,
        )
        scenario = to_canonical(gen, scenario_id)
        result = validate_scenario(scenario, request)  # re-run on the exact stored object
        warnings = ([INJECTION_WARNING] if flags else [])
        rec = DraftRecord(
            draft_id=uuid.uuid4(), version=version, parent_draft_id=parent, created_by=user.id,
            created_at=datetime.now(timezone.utc), request=request.model_dump(mode="json"), scenario=scenario,
            validation=result, prompt_version=prompt.PROMPT_VERSION, model_provider=self.provider.name,
            model_name=self.provider.model_name, warnings=warnings, attempts=attempts,
        )
        self.store.save_draft(rec)
        return rec

    def create_draft(self, request: ScenarioDraftRequest, user: CurrentUser) -> DraftRecord:
        return self._run(request=request, user=user, scenario_id=uuid.uuid4(), version=1, parent=None,
                         feedback=None, previous=None, extra_flags=[])

    def revise(self, draft_id: uuid.UUID, feedback: str, user: CurrentUser) -> DraftRecord:
        prior = self.store.get_draft(draft_id)
        if prior is None or prior.created_by != user.id:
            raise AppError(404, "NOT_FOUND", "Draft not found.")
        request = ScenarioDraftRequest.model_validate(prior.request)
        return self._run(
            request=request, user=user, scenario_id=prior.scenario.id, version=prior.version + 1, parent=prior.draft_id,
            feedback=clean_text(feedback, 2000), previous=prior.scenario.model_dump(mode="json"), extra_flags=[],
        )
