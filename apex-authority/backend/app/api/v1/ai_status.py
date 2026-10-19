from fastapi import APIRouter, Depends

from app.api.v1.deps import get_provider
from app.core.security import CurrentUser, get_current_user
from app.services.ai.provider import DisabledProvider, LLMProvider

router = APIRouter(prefix="/ai", tags=["ai-status"])


@router.get("/status")
def ai_status(_: CurrentUser = Depends(get_current_user), provider: LLMProvider = Depends(get_provider)):
    """No keys, model names or provider error text are exposed."""
    if isinstance(provider, DisabledProvider):
        return {"available": False, "mode": "disabled"}
    return {"available": True, "mode": "mock" if provider.name == "mock" else "live"}
