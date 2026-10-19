"""Shared bounded generate -> parse -> validate -> (retry) loop used by scenario and AAR generation."""
from __future__ import annotations

import json
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.scenario import ValidationIssue
from app.services.ai.provider import (
    LLMProvider, ProviderError, ProviderNotConfigured, ProviderRateLimited, ProviderRejected,
    ProviderTimeout, ProviderUnavailable,
)

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def provider_error_to_app_error(exc: ProviderError) -> AppError:
    """Map provider failures to safe client errors. Never forwards provider text."""
    if isinstance(exc, ProviderNotConfigured):
        return AppError(503, "AI_NOT_CONFIGURED", "The AI service is not available. You can still author scenarios manually.")
    if isinstance(exc, ProviderRateLimited):
        return AppError(429, "AI_RATE_LIMITED", "The AI provider is rate limiting requests. Try again shortly.")
    if isinstance(exc, ProviderTimeout):
        return AppError(503, "AI_TIMEOUT", "The AI provider timed out. Try again.")
    if isinstance(exc, ProviderRejected):
        return AppError(502, "AI_PROVIDER_REJECTED", "The AI provider rejected the request.")
    return AppError(503, "AI_UNAVAILABLE", "The AI provider is temporarily unavailable.")


def parse_output(raw: str, model: type[T]) -> tuple[T | None, list[ValidationIssue]]:
    """Tolerant JSON parse + Pydantic validation. Issues never contain model-supplied values."""
    text = _FENCE.sub("", (raw or "").strip())
    if not text:
        return None, [ValidationIssue(field="$", issue="empty model output")]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, [ValidationIssue(field="$", issue="model output is not valid JSON")]
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        return None, [ValidationIssue(field=".".join(str(p) for p in e["loc"]) or "$", issue=e["msg"]) for e in exc.errors()[:20]]


def generate_validated(
    *,
    provider: LLMProvider,
    settings: Settings,
    system: str,
    build_prompt: Callable[[list[str] | None], str],
    response_model: type[T],
    validate: Callable[[T], list[ValidationIssue]],
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Returns (validated_output, attempts). Total attempts = 1 + settings.effective_max_retries (hard-capped)."""
    max_attempts = 1 + settings.effective_max_retries
    feedback: list[str] | None = None
    last_issues: list[ValidationIssue] = []
    last_provider_error: ProviderError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            raw = provider.generate_json(system_instruction=system, user_prompt=build_prompt(feedback), response_model=response_model)
        except ProviderError as exc:
            if not exc.retryable:
                raise provider_error_to_app_error(exc)
            last_provider_error, last_issues = exc, []
            if attempt < max_attempts:
                sleep(settings.ai_retry_backoff_seconds * attempt)
            continue
        last_provider_error = None
        parsed, issues = parse_output(raw, response_model)
        if parsed is not None:
            issues = validate(parsed)
            if not issues:
                return parsed, attempt
        last_issues = issues
        feedback = [f"{i.field}: {i.issue}" for i in issues]

    if last_provider_error is not None:
        raise provider_error_to_app_error(last_provider_error)
    raise AppError(
        502, "AI_INVALID_OUTPUT",
        "The AI provider returned output that failed validation after the allowed retries. Nothing was saved.",
        [i.model_dump() for i in last_issues[:20]],
    )
