"""Gemini adapter with a fake SDK client: no network, no key, no cost."""
import httpx
import pytest
from google.genai import errors

from app.core.config import Settings, load_settings
from app.schemas.aar import GeneratedAAR
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.provider import (
    DisabledProvider, ProviderNotConfigured, ProviderRateLimited, ProviderRejected, ProviderTimeout,
    ProviderUnavailable, build_provider,
)


class FakeModels:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.kwargs = result, exc, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.result


class FakeClient:
    def __init__(self, **kw):
        self.models = FakeModels(**kw)


class Resp:
    def __init__(self, text): self.text = text


def make(**kw):
    c = FakeClient(**kw)
    return GeminiProvider("SECRET-KEY-123", "some-model", 5, client=c), c


def call(p):
    return p.generate_json(system_instruction="sys", user_prompt="usr", response_model=GeneratedAAR)


def test_success_passes_schema_model_and_timeout():
    p, c = make(result=Resp('{"a": 1}'))
    assert call(p) == '{"a": 1}'
    k = c.models.kwargs
    assert k["model"] == "some-model" and k["contents"] == "usr"
    cfg = k["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_schema is GeneratedAAR
    assert cfg.system_instruction == "sys" and cfg.http_options.timeout == 5000


def test_empty_or_blocked_output_returns_empty_string():
    p, _ = make(result=Resp(None))
    assert call(p) == ""


@pytest.mark.parametrize("code,exc_type", [
    (429, ProviderRateLimited), (503, ProviderUnavailable), (500, ProviderUnavailable),
    (504, ProviderTimeout), (400, ProviderRejected), (403, ProviderRejected),
])
def test_http_errors_are_mapped(code, exc_type):
    cls = errors.ClientError if code < 500 else errors.ServerError
    p, _ = make(exc=cls(code, {"error": {"message": "raw provider text SECRET-KEY-123"}}))
    with pytest.raises(exc_type) as ei:
        call(p)
    assert "SECRET" not in str(ei.value) and "raw provider text" not in str(ei.value)


def test_timeouts_and_network_errors_are_mapped():
    p, _ = make(exc=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout):
        call(p)
    p, _ = make(exc=ConnectionError("boom SECRET-KEY-123"))
    with pytest.raises(ProviderUnavailable) as ei:
        call(p)
    assert "SECRET" not in str(ei.value)


def test_retryable_flags():
    assert ProviderTimeout.retryable and ProviderRateLimited.retryable and ProviderUnavailable.retryable
    assert not ProviderRejected.retryable and not ProviderNotConfigured.retryable


def test_repr_never_leaks_key():
    p, _ = make(result=Resp("{}"))
    assert "SECRET" not in repr(p)
    assert "SECRET" not in repr(Settings(gemini_api_key="SECRET-KEY-123"))


def test_build_provider_modes():
    assert isinstance(build_provider(Settings(ai_provider="disabled")), DisabledProvider)
    assert isinstance(build_provider(Settings(ai_provider="gemini")), DisabledProvider)  # no key/model
    assert isinstance(build_provider(Settings(ai_provider="gemini", gemini_api_key="k")), DisabledProvider)  # no model
    assert isinstance(build_provider(Settings(ai_provider="bogus")), DisabledProvider)
    assert build_provider(Settings(ai_provider="mock")).name == "mock"
    live = build_provider(Settings(ai_provider="gemini", gemini_api_key="k", gemini_model="m"))
    assert live.name == "google" and live.model_name == "m"  # constructed lazily: no network at build time
    with pytest.raises(ProviderNotConfigured):
        DisabledProvider().generate_json()


def test_env_placeholders_are_treated_as_unset(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "replace_with_your_key")
    monkeypatch.setenv("GEMINI_MODEL", "replace_with_supported_model")
    s = load_settings()
    assert s.gemini_api_key is None and s.gemini_model is None
    monkeypatch.setenv("AI_MAX_RETRIES", "99")
    assert load_settings().effective_max_retries == 3
