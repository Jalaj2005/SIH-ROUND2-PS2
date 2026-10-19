"""Dependency wiring. Everything AI-related is injectable so tests (and Module 1) can override it."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, load_settings
from app.core.security import get_settings
from app.services.ai.aar_generation import AARGenerationService
from app.services.ai.provider import LLMProvider, build_provider
from app.services.ai.repository import InMemoryAIStore
from app.services.ai.scenario_generation import ScenarioGenerationService
from app.services.gateways import FixtureSessionGateway, SessionGateway


@lru_cache
def _store() -> InMemoryAIStore:
    return InMemoryAIStore()


@lru_cache
def _provider() -> LLMProvider:
    return build_provider(load_settings())


@lru_cache
def _gateway() -> FixtureSessionGateway:
    return FixtureSessionGateway()


def get_store() -> InMemoryAIStore:
    return _store()


def get_provider() -> LLMProvider:
    return _provider()


def get_session_gateway() -> SessionGateway:
    """Module 1: override this with the real shared session/AAR-input service."""
    return _gateway()


def get_scenario_service(provider: LLMProvider = Depends(get_provider), store: InMemoryAIStore = Depends(get_store),
                         settings: Settings = Depends(get_settings)) -> ScenarioGenerationService:
    return ScenarioGenerationService(provider, store, settings)


def get_aar_service(provider: LLMProvider = Depends(get_provider), store: InMemoryAIStore = Depends(get_store),
                    gateway: SessionGateway = Depends(get_session_gateway),
                    settings: Settings = Depends(get_settings)) -> AARGenerationService:
    return AARGenerationService(provider, store, gateway, settings)
