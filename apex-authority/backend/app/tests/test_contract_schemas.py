"""Confirms the shared spec examples validate against our models, and the business rules behave."""
import json

import pytest
from pydantic import ValidationError

from app.schemas.aar import AARInput, AARReport
from app.schemas.scenario import Scenario, ScenarioDraftRequest
from app.schemas.scenario_rules import validate_scenario
from app.services.gateways import FIXTURE_DIR
from app.tests.conftest import SCENARIO_REQUEST


def load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_spec_scenario_example_is_valid_canonical():
    s = Scenario.model_validate(load("scenario_spec_example.json"))
    assert s.status.value == "draft" and s.schema_version == "1.0"
    assert validate_scenario(s).valid


def test_spec_aar_output_example_is_valid_canonical():
    r = AARReport.model_validate(load("aar_output_spec_example.json"))
    assert r.status.value == "draft" and r.reviewed_by is None


def test_aar_input_fixture_matches_canonical_shape():
    a = AARInput.model_validate(load("aar_input_sample.json"))
    assert a.session_summary.ended_at is not None and len(a.events) == 4 and len(a.decisions) == 2


def test_unknown_enum_values_rejected():
    d = load("scenario_spec_example.json")
    d["domain"] = "space"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)
    d = load("scenario_spec_example.json")
    d["status"] = "published"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)


@pytest.mark.parametrize("mutate,field", [
    (lambda d: d["initial_reports"][0]["visible_to_roles"].append("ghost"), "initial_reports[0].visible_to_roles"),
    (lambda d: d["events"][0].__setitem__("offset_seconds", -1), "events[0].offset_seconds"),
    (lambda d: d["events"][0].__setitem__("offset_seconds", 99999), "events[0].offset_seconds"),
    (lambda d: d["events"][0]["config"].__setitem__("failure_type", "explode"), "events[0].config.failure_type"),
    (lambda d: d["events"][0]["config"]["target_roles"].append("ghost"), "events[0].config.target_roles"),
    (lambda d: d["decision_points"][0]["options"].pop(), "decision_points[0].options"),
    (lambda d: d["decision_points"][0]["evaluation_criteria"][0]["acceptable_option_ids"].append("Z"),
     "decision_points[0].evaluation_criteria[0].acceptable_option_ids"),
    (lambda d: d["decision_points"][0]["evaluation_criteria"][0].__setitem__("weight", 0), "decision_points[0].evaluation_criteria[0].weight"),
    (lambda d: d["decision_points"][0].__setitem__("visible_to_roles", ["ghost"]), "decision_points[0].visible_to_roles"),
    (lambda d: d.__setitem__("status", "approved"), "status"),
])
def test_business_rules_reject(mutate, field):
    d = load("scenario_spec_example.json")
    mutate(d)
    res = validate_scenario(Scenario.model_validate(d))
    assert not res.valid and any(e.field == field for e in res.errors), res.errors


def test_duplicate_keys_rejected():
    d = load("scenario_spec_example.json")
    d["roles"].append(dict(d["roles"][0]))
    d["decision_points"].append(dict(d["decision_points"][0]))
    res = validate_scenario(Scenario.model_validate(d))
    msgs = " ".join(e.issue for e in res.errors)
    assert "duplicate role_id" in msgs and "duplicate decision_key" in msgs


def test_request_mismatch_detected():
    d = load("scenario_spec_example.json")
    d["duration_minutes"] = 30
    d["domain"] = "cyber"
    d["difficulty"] = "advanced"
    req = ScenarioDraftRequest.model_validate(SCENARIO_REQUEST)
    res = validate_scenario(Scenario.model_validate(d), req)
    assert {"roles", "duration_minutes", "domain", "difficulty"} <= {e.field for e in res.errors}
    # requested failure types that are not scheduled are warnings, not errors
    assert any("drop" in w.issue for w in res.warnings)


@pytest.mark.parametrize("patch", [
    {"role_count": 3},
    {"role_ids": ["Commander", "intel", "ops", "comms"]},
    {"duration_minutes": 1},
    {"duration_minutes": 500},
    {"communication_failures": []},
    {"domain": "space"},
    {"learning_objectives": []},
    {"unexpected": "field"},
    {"constraints": ["x" * 301]},
])
def test_request_validation(patch):
    with pytest.raises(ValidationError):
        ScenarioDraftRequest.model_validate({**SCENARIO_REQUEST, **patch})
