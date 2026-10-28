"""Application list / detail / create / patch endpoints."""
import pytest

INST_A = "institution.user@example.test"
INST_B = "institution.user.b@example.test"
SCRUTINY = "scrutiny.officer@example.test"
ADMIN = "admin@example.test"
MGMT = "management.viewer@example.test"
BASE = "/api/v1/applications"


def test_list_requires_authentication(client):
    assert client.get(BASE).status_code == 401


def test_list_uses_shared_paged_envelope_and_is_scoped(client, login):
    r = client.get(BASE, headers=login(INST_A))
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["page"] == 1 and body["meta"]["page_size"] == 20 and body["meta"]["request_id"]
    assert {a["id"] for a in body["data"]} == {"app_001", "app_002", "app_005"}  # inst_001's cases only (incl. its draft)
    assert body["meta"]["total"] == 3


def test_list_item_shape(client, login):
    item = next(a for a in client.get(BASE, headers=login(SCRUTINY)).json()["data"] if a["id"] == "app_001")
    assert item["application_number"] == "APP-2026-0001"
    assert item["status"] == "IN_SCRUTINY" and item["current_stage"]["stage_code"] == "IN_SCRUTINY"
    assert item["assigned_to"] == "usr_scrutiny" and item["assigned_to_name"] == "Scrutiny Officer"
    assert item["responsible_roles"] == ["SCRUTINY_OFFICER"]
    assert item["institution_name"] == "Demo Institute of Technology A"
    assert item["stage_entered_at"] and item["stage_due_at"] > item["stage_entered_at"]  # 120h demo SLA
    assert item["submitted_at"]


def test_list_filters(client, login):
    h = login(ADMIN)
    ids = lambda qs: sorted(a["id"] for a in client.get(f"{BASE}?{qs}", headers=h).json()["data"])  # noqa: E731
    assert ids("status=IN_SCRUTINY") == ["app_001", "app_004"]
    assert ids("stage=EVC_PENDING") == ["app_003"]
    assert ids("institution_id=inst_002") == ["app_004"]
    assert ids("assigned_to=usr_scrutiny") == ["app_001"]
    assert ids("category=EXTENSION_OF_APPROVAL") == ["app_002"]
    assert ids("q=APP-2026-0003") == ["app_003"]
    assert ids("q=management B") == ["app_004"]
    assert ids("status=NO_SUCH_STATUS") == []
    assert ids("status=IN_SCRUTINY&institution_id=inst_001") == ["app_001"]


def test_assigned_to_me(client, login):
    r = client.get(f"{BASE}?assigned_to=me", headers=login(SCRUTINY))
    assert [a["id"] for a in r.json()["data"]] == ["app_001"]


def test_list_pagination_and_bounds(client, login):
    h = login(ADMIN)
    first = client.get(f"{BASE}?page_size=2", headers=h).json()
    assert len(first["data"]) == 2 and first["meta"]["total"] == 4 and first["meta"]["page_size"] == 2
    assert len(client.get(f"{BASE}?page_size=2&page=2", headers=h).json()["data"]) == 2
    assert client.get(f"{BASE}?page=9", headers=h).json()["data"] == []
    assert client.get(f"{BASE}?page_size=101", headers=h).status_code == 422


def test_detail_includes_open_deficiency_only_when_returned(client, login):
    returned = client.get(f"{BASE}/app_002", headers=login(INST_A)).json()["data"]
    d = returned["open_deficiency"]
    assert d["reason"] == "Lease document is missing an authorised signature."
    assert d["checklist_code"] == "LEASE_SIGNATURE" and d["returned_by"]["id"] == "usr_scrutiny"
    assert client.get(f"{BASE}/app_001", headers=login(INST_A)).json()["data"]["open_deficiency"] is None


def test_detail_404_for_missing(client, login):
    r = client.get(f"{BASE}/app_nope", headers=login(ADMIN))
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


# ---- create

def test_create_draft(client, login):
    r = client.post(BASE, json={"category": "new_institution"}, headers=login(INST_A))
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["status"] == "DRAFT" and d["category"] == "NEW_INSTITUTION" and d["institution_id"] == "inst_001"
    assert d["application_number"].startswith("APP-") and d["submitted_at"] is None and d["assigned_to"] is None
    hist = client.get(f"{BASE}/{d['id']}/history", headers=login(INST_A)).json()["data"]
    assert [h["action"] for h in hist] == ["CREATE"] and hist[0]["actor"]["id"] == "usr_institution_a"


def test_create_and_submit_routes_to_scrutiny(client, login):
    r = client.post(BASE, json={"category": "EXTENSION_OF_APPROVAL", "submit": True}, headers=login(INST_A))
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["status"] == "IN_SCRUTINY" and d["assigned_to"] == "usr_scrutiny" and d["submitted_at"]
    hist = client.get(f"{BASE}/{d['id']}/history", headers=login(INST_A)).json()["data"]
    assert [h["action"] for h in hist] == ["CREATE", "SUBMIT", "ROUTE_TO_SCRUTINY"]
    assert hist[2]["metadata"]["auto"] is True and hist[2]["metadata"]["triggered_by_action"] == "SUBMIT"


def test_create_validation_and_permissions(client, login):
    h = login(INST_A)
    assert client.post(BASE, json={"category": "NO_SUCH_CATEGORY"}, headers=h).status_code == 422
    assert client.post(BASE, json={}, headers=h).status_code == 422
    assert client.post(BASE, json={"category": "NEW_INSTITUTION", "institution_id": "inst_002"}, headers=h).status_code == 403
    assert client.post(BASE, json={"category": "NEW_INSTITUTION", "institution_id": "inst_001"}, headers=h).status_code == 201
    for email in (SCRUTINY, ADMIN, MGMT):
        r = client.post(BASE, json={"category": "NEW_INSTITUTION"}, headers=login(email))
        assert r.status_code == 403, email
    assert client.post(BASE, json={"category": "NEW_INSTITUTION"}).status_code == 401


@pytest.mark.parametrize("field,value", [("status", "APPROVED"), ("current_stage_id", "stg_x"), ("assigned_to", "usr_admin")])
def test_create_cannot_set_engine_owned_fields(client, login, field, value):
    r = client.post(BASE, json={"category": "NEW_INSTITUTION", field: value}, headers=login(INST_A))
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---- patch: never status / stage

@pytest.mark.parametrize(
    "body",
    [
        {"status": "APPROVED"},
        {"current_stage_id": "stg_new_institution_approved"},
        {"workflow_template_id": "wft_extension_of_approval_v1"},
        {"assigned_to": "usr_admin"},
        {"category": "EXTENSION_OF_APPROVAL", "status": "APPROVED"},  # valid field + forbidden field => whole request refused
        {"application_number": "APP-HACK"},
    ],
)
def test_patch_rejects_direct_status_or_stage_changes(client, login, session_factory, body):
    from app.models import Application

    h = login(INST_A)
    r = client.patch(f"{BASE}/app_005", json=body, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    with session_factory() as s:
        a = s.get(Application, "app_005")
        assert (a.status, a.category) == ("DRAFT", "EXTENSION_OF_APPROVAL")


def test_patch_message_points_to_transition_endpoint(client, login):
    r = client.patch(f"{BASE}/app_005", json={"status": "APPROVED"}, headers=login(INST_A))
    assert "transitions" in r.text


def test_patch_category_on_draft_reselects_template_and_is_audited(client, login):
    h = login(INST_A)
    r = client.patch(f"{BASE}/app_005", json={"category": "NEW_INSTITUTION"}, headers=h)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["category"] == "NEW_INSTITUTION" and d["workflow_template_id"] == "wft_new_institution_v1"
    assert d["status"] == "DRAFT" and d["current_stage"]["id"] == "stg_new_institution_draft"
    hist = client.get(f"{BASE}/app_005/history", headers=h).json()["data"]
    audit = [e for e in hist if e["entry_type"] == "AUDIT_EVENT"]
    assert audit and audit[0]["action"] == "APPLICATION_UPDATED"
    assert audit[0]["metadata"]["before"]["category"] == "EXTENSION_OF_APPROVAL"


def test_patch_only_while_draft_and_by_owner(client, login):
    assert client.patch(f"{BASE}/app_001", json={"category": "NEW_INSTITUTION"}, headers=login(INST_A)).status_code == 409
    assert client.patch(f"{BASE}/app_005", json={}, headers=login(INST_A)).status_code == 422
    assert client.patch(f"{BASE}/app_005", json={"category": "NOPE"}, headers=login(INST_A)).status_code == 422
    assert client.patch(f"{BASE}/app_005", json={"category": "NEW_INSTITUTION"}, headers=login(INST_B)).status_code == 403
    assert client.patch(f"{BASE}/app_005", json={"category": "NEW_INSTITUTION"}, headers=login(SCRUTINY)).status_code == 403
    assert client.patch(f"{BASE}/app_005", json={"category": "NEW_INSTITUTION"}).status_code == 401


def test_workflow_templates_endpoint(client, login):
    r = client.get("/api/v1/workflow-templates", headers=login(INST_A))
    assert r.status_code == 200
    by_cat = {t["category"]: t for t in r.json()["data"]}
    assert set(by_cat) == {"NEW_INSTITUTION", "EXTENSION_OF_APPROVAL"}
    new, ext = by_cat["NEW_INSTITUTION"], by_cat["EXTENSION_OF_APPROVAL"]
    assert "EVC_PENDING" in {s["stage_code"] for s in new["stages"]}
    assert "EVC_PENDING" not in {s["stage_code"] for s in ext["stages"]}
    assert any(t["required_role"] == "SYSTEM" and t["action"] == "ROUTE_TO_SCRUTINY" for t in new["transitions"])
    assert client.get("/api/v1/workflow-templates").status_code == 401


def test_openapi_exposes_module1_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/applications", "/api/v1/applications/{application_id}",
        "/api/v1/applications/{application_id}/history", "/api/v1/applications/{application_id}/allowed-actions",
        "/api/v1/applications/{application_id}/transitions", "/api/v1/workflow-templates",
    ):
        assert path in paths
    assert "put" not in paths["/api/v1/applications/{application_id}"]
