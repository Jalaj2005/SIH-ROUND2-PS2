"""Gemini implementation using the official Google Gen AI SDK (`google-genai`). Server-side only."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.services.ai.provider import (
    ProviderRateLimited, ProviderRejected, ProviderTimeout, ProviderUnavailable,
)


class GeminiProvider:
    name = "google"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 30.0, client: Any | None = None,
                 temperature: float = 0.4, max_output_tokens: int = 8192):
        self.model_name = model_name
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client  # injectable for tests
        self._temperature = temperature
        self._max_tokens = max_output_tokens

    def __repr__(self) -> str:  # never leak the key
        return f"GeminiProvider(model={self.model_name!r})"

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_json(self, *, system_instruction: str, user_prompt: str, response_model: type[BaseModel]) -> str:
        from google.genai import errors, types
        import httpx

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
            http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),  # milliseconds
        )
        try:
            response = self._get_client().models.generate_content(
                model=self.model_name, contents=user_prompt, config=config
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                raise ProviderRateLimited("Provider rate limit reached.") from None
            if code in (408, 504):
                raise ProviderTimeout("Provider request timed out.") from None
            if isinstance(code, int) and 400 <= code < 500:
                raise ProviderRejected(f"Provider rejected the request (HTTP {code}).") from None
            raise ProviderUnavailable("Provider is temporarily unavailable.") from None
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderTimeout("Provider request timed out.") from None
        except Exception as exc:  # network errors, SDK internals: surface a generic, safe message
            if "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower():
                raise ProviderTimeout("Provider request timed out.") from None
            raise ProviderUnavailable("Provider is temporarily unavailable.") from None

        text = getattr(response, "text", None)
        return text or ""  # empty/blocked output is treated by callers as invalid output
