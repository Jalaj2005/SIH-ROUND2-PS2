"""Provider abstraction. Services depend only on `LLMProvider`; Gemini is one implementation."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ProviderError(Exception):
    """Base for all provider failures. Messages must be safe to log (no keys, no prompts)."""
    retryable = False


class ProviderNotConfigured(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderRejected(ProviderError):
    """4xx other than 429: request itself was refused (bad model name, auth, safety). Not retried."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str          # e.g. "google", "mock"
    model_name: str    # configuration/metadata, never hardcoded

    def generate_json(self, *, system_instruction: str, user_prompt: str, response_model: type[BaseModel]) -> str:
        """Return raw JSON text intended to satisfy `response_model`. Callers must re-validate."""
        ...


class DisabledProvider:
    """Used when AI is switched off or not configured. Every call fails safely."""
    name = "disabled"
    model_name = "none"

    def __init__(self, reason: str = "AI service is disabled."):
        self.reason = reason

    def generate_json(self, **_: object) -> str:
        raise ProviderNotConfigured(self.reason)


def build_provider(settings) -> LLMProvider:
    mode = settings.ai_provider
    if mode == "disabled":
        return DisabledProvider("AI service is disabled.")
    if mode == "mock":
        from app.services.ai.mock_provider import FixtureProvider
        return FixtureProvider()
    if mode == "gemini":
        if not settings.gemini_api_key or not settings.gemini_model:
            return DisabledProvider("Gemini is not configured (GEMINI_API_KEY / GEMINI_MODEL).")
        from app.services.ai.gemini_provider import GeminiProvider
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds)
    return DisabledProvider(f"Unknown AI_PROVIDER '{mode}'.")
