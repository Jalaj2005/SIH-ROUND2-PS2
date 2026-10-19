import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import deps
from app.core.config import Settings
from app.core.security import get_settings
from app.main import create_app
from app.schemas.aar import AARInput
from app.services.ai.mock_provider import FixtureProvider, ScriptedProvider
from app.services.ai.repository import InMemoryAIStore
from app.services.gateways import FIXTURE_DIR, FixtureSessionGateway

INSTRUCTOR = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
OTHER_INSTRUCTOR = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
TRAINEE = uuid.UUID("00000000-0000-0000-0000-0000000000b1")

SCENARIO_REQUEST = {  # spec 8.1
    "domain": "joint_operations",
    "learning_objectives": ["maintain shared situation awareness"],
    "difficulty": "intermediate", "duration_minutes": 20, "role_count": 4,
    "role_ids": ["commander", "intelligence", "communications", "operations"],
    "communication_failures": ["delay", "drop", "conflicting_report"],
    "constraints": ["fictional setting", "instructor approval required"],
}


def headers(user=INSTRUCTOR, role="instructor"):
    return {"X-Demo-User-Id": str(user), "X-Demo-Role": role}


def load_aar_input() -> dict:
    return json.loads((FIXTURE_DIR / "aar_input_sample.json").read_text())


def valid_generated_scenario(request: dict | None = None) -> dict:
    """A schema- and rule-valid model output for the given request (reuses the offline fixture builder)."""
    req = request or SCENARIO_REQUEST
    out = FixtureProvider()._scenario([{"requirements": req}])
    return out


def valid_generated_aar(aar_input: dict | None = None, **overrides) -> dict:
    d = aar_input or load_aar_input()
    ev, dec = d["events"], d["decisions"]
    out = {
        "title": "After-Action Review",
        "executive_summary": "The team handled delayed and conflicting reports; two decisions were recorded.",
        "key_observations": [
            {"observation": "A message to the commander was delayed.", "classification": "fact",
             "evidence_refs": [ev[0]["event_id"]], "confidence": "high"},
            {"observation": "The second decision was made after a dropout, possibly with less confirmation.",
             "classification": "interpretation", "evidence_refs": [dec[1]["decision_id"], ev[2]["event_id"]], "confidence": "medium"},
        ],
        "strengths": [{"text": "Confirmation was requested under incomplete evidence.", "evidence_refs": [dec[0]["decision_id"]]}],
        "improvement_areas": [{"text": "Acknowledge delayed reports explicitly.", "evidence_refs": [ev[0]["event_id"], "communication_delivery_rate"]}],
        "recommendations": [{"text": "Practise acknowledgement of delayed reports.",
                             "related_learning_objective": d["scenario"]["learning_objectives"][1]}],
        "evidence_limitations": ["No voice transcript was recorded."],
        "follow_up_scenario_brief": "Short follow-up emphasising confirmation of critical updates.",
    }
    out.update(overrides)
    return out


@pytest.fixture
def settings():
    return Settings(app_env="test", ai_provider="mock", ai_max_retries=1, ai_retry_backoff_seconds=0.0)


@pytest.fixture
def provider():
    return ScriptedProvider()


@pytest.fixture
def gateway():
    return FixtureSessionGateway()


@pytest.fixture
def store():
    return InMemoryAIStore()


@pytest.fixture
def app(settings, provider, gateway, store):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.get_provider] = lambda: provider
    app.dependency_overrides[deps.get_session_gateway] = lambda: gateway
    app.dependency_overrides[deps.get_store] = lambda: store
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def aar_input_dict():
    return load_aar_input()


@pytest.fixture
def session_id(aar_input_dict):
    return aar_input_dict["session_id"]
