"""Role + record-scope enforcement on every Module 1 endpoint (server side, not UI)."""
import pytest
from sqlalchemy import select

from app.models import Application, ApplicationStageHistory

INST_A = "institution.user@example.test"      # inst_001 (reg_central)
INST_B = "institution.user.b@example.test"    # inst_002 (reg_west)
SCRUTINY = "scrutiny.officer@example.test"    # reg_central
EVC = "evc.coordinator@example.test"
COMPLIANCE = "compliance.officer@example.test"
REGIONAL = "regional.officer@example.test"
COMMITTEE = "committee.authority@example.test"
ADMIN = "admin@example.test"
MGMT = "management.viewer@example.test"
BASE = "/api/v1/applications"

A_APPS = {"app_001", "app_002", "app_005"}     # inst_001 (app_005 is a draft)
B_APP = "app_004"                              # inst_002


def ids(client, email, login, qs=""):
    return {a["id"] for a in client.get(f"{BASE}{qs}", headers=login(email)).json()["data"]}


def test_institution_list_shows_only_own_cases(client, login):
    assert ids(client, INST_A, login) == A_APPS
    assert ids(client, INST_B, login) == {B_APP}


def test_institution_filter_cannot_widen_scope(client, login):
    assert ids(client, INST_A, login, "?institution_id=inst_002") == set()
    assert ids(client, INST_A, login, "?q=Management") == set()
    assert ids(client, INST_B, login, "?assigned_to=usr_scrutiny") == set()


@pytest.mark.parametrize("path", ["", "/history", "/allowed-actions"])
def test_institution_cannot_read_another_institutions_case_by_changing_the_id(client, login, path):
    r = client.get(f"{BASE}/app_001{path}", headers=login(INST_B))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert "Demo Institute" not in r.text and "APP-2026-0001" not in r.text  # nothing leaks through the error
    r = client.get(f"{BASE}/{B_APP}{path}", headers=login(INST_A))
    assert r.status_code == 403


def test_institution_cannot_mutate_another_institutions_case(client, login, session_factory):
    for action, reason in (("WITHDRAW", "x"), ("RESUBMIT", "x"), ("SUBMIT", None)):
        body = {"action": action, **({"reason": reason} if reason else {})}
        for app_id in ("app_001", "app_002", "app_005"):
            assert client.post(f"{BASE}/{app_id}/transitions", json=body, headers=login(INST_B)).status_code == 403
    assert client.patch(f"{BASE}/app_005", json={"category": "NEW_INSTITUTION"}, headers=login(INST_B)).status_code == 403
    with session_factory() as s:
        assert {a.id: a.status for a in s.scalars(select(Application))} == {
            "app_001": "IN_SCRUTINY", "app_002": "RETURNED_FOR_DEFICIENCY", "app_003": "EVC_PENDING",
            "app_004": "IN_SCRUTINY", "app_005": "DRAFT",
        }
        assert len(s.scalars(select(ApplicationStageHistory).where(ApplicationStageHistory.action == "WITHDRAW")).all()) == 0


@pytest.mark.parametrize("email", [SCRUTINY, EVC, COMPLIANCE, REGIONAL, COMMITTEE])
def test_region_scoped_officers_see_only_their_region_and_no_drafts(client, login, email):
    got = ids(client, email, login)
    assert got == {"app_001", "app_002", "app_003"}  # reg_central; not inst_002's case, not inst_001's draft
    assert client.get(f"{BASE}/{B_APP}", headers=login(email)).status_code == 403
    assert client.get(f"{BASE}/app_005", headers=login(email)).status_code == 403  # draft is private to the institution
    assert client.get(f"{BASE}/app_005/history", headers=login(email)).status_code == 403


def test_out_of_region_officer_cannot_act(client, login, session_factory):
    r = client.post(f"{BASE}/{B_APP}/transitions", json={"action": "COMPLETE_SCRUTINY"}, headers=login(SCRUTINY))
    assert r.status_code == 403
    assert client.get(f"{BASE}/{B_APP}/allowed-actions", headers=login(SCRUTINY)).status_code == 403
    with session_factory() as s:
        assert s.get(Application, B_APP).status == "IN_SCRUTINY"


def test_management_and_admin_see_all_submitted_cases_but_never_drafts(client, login):
    for email in (MGMT, ADMIN):
        assert ids(client, email, login) == {"app_001", "app_002", "app_003", "app_004"}
        assert client.get(f"{BASE}/app_005", headers=login(email)).status_code == 403


def test_missing_case_is_404_for_every_endpoint(client, login):
    h = login(ADMIN)
    assert client.get(f"{BASE}/app_nope", headers=h).status_code == 404
    assert client.get(f"{BASE}/app_nope/history", headers=h).status_code == 404
    assert client.get(f"{BASE}/app_nope/allowed-actions", headers=h).status_code == 404
    assert client.post(f"{BASE}/app_nope/transitions", json={"action": "SUBMIT"}, headers=login(INST_A)).status_code == 404


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", BASE, None),
        ("post", BASE, {"category": "NEW_INSTITUTION"}),
        ("get", f"{BASE}/app_001", None),
        ("patch", f"{BASE}/app_005", {"category": "NEW_INSTITUTION"}),
        ("get", f"{BASE}/app_001/history", None),
        ("get", f"{BASE}/app_001/allowed-actions", None),
        ("post", f"{BASE}/app_001/transitions", {"action": "COMPLETE_SCRUTINY"}),
        ("get", "/api/v1/workflow-templates", None),
    ],
)
def test_every_module1_endpoint_requires_authentication(client, method, path, body):
    r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_deactivated_user_loses_access_immediately(client, login, session_factory):
    from app.models import User

    h = login(INST_A)
    assert client.get(BASE, headers=h).status_code == 200
    with session_factory() as s:
        s.get(User, "usr_institution_a").is_active = False
        s.commit()
    assert client.get(BASE, headers=h).status_code == 401


def test_institution_user_without_institution_fails_closed(client, login, session_factory):
    from app.models import User

    h = login(INST_A)
    with session_factory() as s:
        s.get(User, "usr_institution_a").institution_id = None
        s.commit()
    assert client.get(BASE, headers=h).json()["data"] == []
    assert client.post(BASE, json={"category": "NEW_INSTITUTION"}, headers=h).status_code == 403
    assert client.get(f"{BASE}/app_001", headers=h).status_code == 403
