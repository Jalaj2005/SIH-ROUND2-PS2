import json

from app.api.v1 import deps
from app.core.config import Settings
from app.core.security import get_settings
from app.services.ai.mock_provider import FixtureProvider
from app.services.ai.provider import DisabledProvider
from app.tests.conftest import SCENARIO_REQUEST, headers, valid_generated_scenario

SECRET = "SECRET-KEY-DO-NOT-LEAK"


def test_status_modes_reveal_no_secrets(client, app):
    h = headers()
    assert client.get("/api/v1/ai/status").status_code == 401
    app.dependency_overrides[deps.get_provider] = lambda: DisabledProvider(f"missing {SECRET}")
    r = client.get("/api/v1/ai/status", headers=h)
    assert r.json() == {"available": False, "mode": "disabled"} and SECRET not in r.text
    app.dependency_overrides[deps.get_provider] = lambda: FixtureProvider()
    assert client.get("/api/v1/ai/status", headers=h).json() == {"available": True, "mode": "mock"}
    from app.services.ai.gemini_provider import GeminiProvider
    app.dependency_overrides[deps.get_provider] = lambda: GeminiProvider(SECRET, "model-x")
    body = client.get("/api/v1/ai/status", headers=h).json()
    assert body == {"available": True, "mode": "live"} and "model-x" not in json.dumps(body)


def test_app_runs_without_any_gemini_configuration(monkeypatch):
    """Module 1 must run with no key; Module 2 must degrade cleanly rather than crash at import/startup."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    from fastapi.testclient import TestClient
    from app.main import create_app
    deps._provider.cache_clear()
    c = TestClient(create_app(), raise_server_exceptions=False)
    assert c.get("/health").status_code == 200
    h = headers()
    assert c.get("/api/v1/ai/status", headers=h).json() == {"available": False, "mode": "disabled"}
    r = c.post("/api/v1/ai/scenario-drafts", json=SCENARIO_REQUEST, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    deps._provider.cache_clear()


def test_provider_error_text_and_prompts_never_reach_clients(client, provider):
    from app.services.ai.provider import ProviderUnavailable
    provider.queue(ProviderUnavailable(f"upstream said {SECRET}"), ProviderUnavailable(f"upstream said {SECRET}"))
    r = client.post("/api/v1/ai/scenario-drafts", json=SCENARIO_REQUEST, headers=headers())
    assert SECRET not in r.text and "untrusted_input" not in r.text


def test_unhandled_exception_returns_standard_envelope(app, client, provider):
    def boom():
        raise RuntimeError(f"db password {SECRET}")
    app.dependency_overrides[deps.get_store] = boom
    r = client.post("/api/v1/ai/scenario-drafts", json=SCENARIO_REQUEST, headers=headers())
    assert r.status_code == 500 and SECRET not in r.text
    assert r.json()["error"]["code"] == "INTERNAL_ERROR" and r.json()["error"]["request_id"]


def test_request_id_header_and_envelope_match(client):
    r = client.get("/api/v1/ai/scenario-drafts/00000000-0000-0000-0000-000000000001", headers=headers())
    assert r.status_code == 404 and r.json()["error"]["request_id"] == r.headers["x-request-id"]
