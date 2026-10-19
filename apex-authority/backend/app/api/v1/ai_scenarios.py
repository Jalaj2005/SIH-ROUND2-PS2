import uuid

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_scenario_service, get_store
from app.core.errors import AppError
from app.core.security import CurrentUser, require_instructor
from app.schemas.scenario import ScenarioDraftRequest, ScenarioDraftResponse, ScenarioReviseRequest
from app.services.ai.repository import DraftRecord, InMemoryAIStore
from app.services.ai.scenario_generation import ScenarioGenerationService

router = APIRouter(prefix="/ai/scenario-drafts", tags=["ai-scenarios"])


def _out(rec: DraftRecord) -> ScenarioDraftResponse:
    return ScenarioDraftResponse(
        draft_id=rec.draft_id, version=rec.version, parent_draft_id=rec.parent_draft_id, scenario=rec.scenario,
        validation=rec.validation, status=rec.scenario.status, prompt_version=rec.prompt_version,
        model_provider=rec.model_provider, model_name=rec.model_name, warnings=rec.warnings,
        created_at=rec.created_at.isoformat().replace("+00:00", "Z"),
    )


@router.post("", status_code=201, response_model=ScenarioDraftResponse)
def create_draft(body: ScenarioDraftRequest, user: CurrentUser = Depends(require_instructor),
                 svc: ScenarioGenerationService = Depends(get_scenario_service)):
    return _out(svc.create_draft(body, user))


@router.get("/{draft_id}", response_model=ScenarioDraftResponse)
def get_draft(draft_id: uuid.UUID, user: CurrentUser = Depends(require_instructor),
              store: InMemoryAIStore = Depends(get_store)):
    rec = store.get_draft(draft_id)
    if rec is None or rec.created_by != user.id:
        raise AppError(404, "NOT_FOUND", "Draft not found.")
    return _out(rec)


@router.post("/{draft_id}/revise", status_code=201, response_model=ScenarioDraftResponse)
def revise_draft(draft_id: uuid.UUID, body: ScenarioReviseRequest, user: CurrentUser = Depends(require_instructor),
                 svc: ScenarioGenerationService = Depends(get_scenario_service)):
    return _out(svc.revise(draft_id, body.feedback, user))
