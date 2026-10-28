"""Validated transitions, required reasons, resubmission, allowed-actions, history and audit (HTTP level)."""
import pytest
from sqlalchemy import select

from app.models import Application, ApplicationStageHistory, AuditLog, Document, User

INST_A = "institution.user@example.test"
SCRUTINY = "scrutiny.officer@example.test"
COMMITTEE = "committee.authority@example.test"
REGIONAL = "regional.officer@example.test"
EVC = "evc.coordinator@example.test"
ADMIN = "admin@example.test"
MGMT = "management.viewer@example.test"
BASE = "/api/v1/applications"


@pytest.fixture()
def act(client, login):
    def _act(email, app_id, action, reason=None, metadata=None, **extra):
        body = {"action": action, **extra}
        if reason is not None:
            body["reason"] = reason
        if metadata is not None:
            body["metadata"] = metadata
        return client.post(f"{BASE}/{app_id}/transitions", json=body, headers=login(email))

    return _act


@pytest.fixture()
def allowed(client, login):
    def _allowed(email, app_id):
        r = client.get(f"{BASE}/{app_id}/allowed-actions", headers=login(email))
        assert r.status_code == 200, r.text
        return {a["action"]: a for a in r.json()["data"]["actions"]}

    return _allowed


def _status(session_factory, app_id):
    with session_factory() as s:
        return s.get(Application, app_id).status


# ------------------------------------------------------------------ the demo journey (P0)

def test_full_demo_journey_submit_return_resubmit_next_stage_decision(client, login, act, allowed, session_factory):
    """submit -> scrutiny -> return with reason -> resubmit -> next stage -> authorised outcome (EXTENSION route)."""
    # 1. institution creates + submits; engine routes to scrutiny and assigns the regional scrutiny officer
    r = client.post(BASE, json={"category": "EXTENSION_OF_APPROVAL", "submit": True}, headers=login(INST_A))
    assert r.status_code == 201
    app_id = r.json()["data"]["id"]
    d = r.json()["data"]
    assert (d["status"], d["assigned_to"]) == ("IN_SCRUTINY", "usr_scrutiny")

    # 2. scrutiny officer sees exactly the permitted buttons, and a return needs a reason
    acts = allowed(SCRUTINY, app_id)
    assert set(acts) == {"RETURN_FOR_DEFICIENCY", "COMPLETE_SCRUTINY"} and acts["RETURN_FOR_DEFICIENCY"]["requires_reason"]
    missing = act(SCRUTINY, app_id, "RETURN_FOR_DEFICIENCY")
    assert missing.status_code == 422
    assert missing.json()["error"]["details"] == [{"field": "reason", "issue": "required"}]
    assert _status(session_factory, app_id) == "IN_SCRUTINY"

    r = act(SCRUTINY, app_id, "RETURN_FOR_DEFICIENCY", "Lease document is missing an authorised signature.",
            {"checklist_code": "LEASE_SIGNATURE"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "RETURNED_FOR_DEFICIENCY" and d["assigned_to"] is None
    assert d["open_deficiency"]["reason"].startswith("Lease document") and d["responsible_roles"] == ["INSTITUTION_USER"]

    # 3. institution sees the deficiency, resubmits with a response and an evidence reference
    assert set(allowed(INST_A, app_id)) == {"RESUBMIT", "WITHDRAW"}
    assert act(INST_A, app_id, "RESUBMIT").status_code == 422  # response is required
    bad = act(INST_A, app_id, "RESUBMIT", "Signed lease attached.", {"document_ids": ["doc_nope"]})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "metadata.document_ids"
    with session_factory() as s:
        s.add(Document(id="doc_lease1", institution_id="inst_001", application_id=app_id, document_type="LEASE",
                       filename="lease_signed.pdf", storage_key="synthetic/lease_signed.pdf", uploaded_by="usr_institution_a"))
        s.commit()
    r = act(INST_A, app_id, "RESUBMIT", "Signed lease attached.", {"document_ids": ["doc_lease1"]})
    assert r.status_code == 200
    d = r.json()["data"]
    # engine routed RESUBMITTED -> RE_SCRUTINY and kept the same officer for continuity
    assert (d["status"], d["assigned_to"]) == ("RE_SCRUTINY", "usr_scrutiny")

    # 4. scrutiny completes; this template has no EVC/committee so it goes to the authority
    r = act(SCRUTINY, app_id, "COMPLETE_SCRUTINY")
    assert r.status_code == 200 and r.json()["data"]["status"] == "AWAITING_AUTHORITY_DECISION"

    # 5. only the authority can record the outcome, with a reason; admin / institution / scrutiny cannot
    for email in (INST_A, SCRUTINY, ADMIN, MGMT):
        assert act(email, app_id, "RECORD_APPROVAL", "x").status_code == 403, email
    assert act(COMMITTEE, app_id, "RECORD_APPROVAL").status_code == 422
    r = act(COMMITTEE, app_id, "RECORD_APPROVAL", "Recorded by the competent authority (demo).")
    assert r.status_code == 200 and r.json()["data"]["status"] == "APPROVED"
    assert act(REGIONAL, app_id, "CLOSE").json()["data"]["status"] == "CLOSED"

    # 6. history: every step has actor + timestamp, is chronological and agrees with the final status
    hist = client.get(f"{BASE}/{app_id}/history", headers=login(INST_A)).json()["data"]
    assert [h["action"] for h in hist] == [
        "CREATE", "SUBMIT", "ROUTE_TO_SCRUTINY", "RETURN_FOR_DEFICIENCY", "RESUBMIT", "ROUTE_TO_RE_SCRUTINY",
        "COMPLETE_SCRUTINY", "RECORD_APPROVAL", "CLOSE",
    ]
    assert all(h["actor"] and h["created_at"] for h in hist)
    assert [h["created_at"] for h in hist] == sorted(h["created_at"] for h in hist)
    assert hist[-1]["to_stage"] == "CLOSED"
    returned = next(h for h in hist if h["action"] == "RETURN_FOR_DEFICIENCY")
    assert returned["actor"]["name"] == "Scrutiny Officer" and returned["metadata"]["checklist_code"] == "LEASE_SIGNATURE"
    resub = next(h for h in hist if h["action"] == "RESUBMIT")
    assert resub["metadata"]["responds_to"] == returned["id"] and resub["metadata"]["document_ids"] == ["doc_lease1"]

    # 7. audit: one APPLICATION_TRANSITION row per stage change (auto steps included), same actor/reason
    with session_factory() as s:
        rows = s.scalars(select(AuditLog).where(AuditLog.entity_id == app_id, AuditLog.action == "APPLICATION_TRANSITION")).all()
        n_stage_changes = len(s.scalars(select(ApplicationStageHistory).where(
            ApplicationStageHistory.application_id == app_id, ApplicationStageHistory.action != "CREATE")).all())
        assert len(rows) == n_stage_changes == 8
        ret = next(r for r in rows if r.after_json["workflow_action"] == "RETURN_FOR_DEFICIENCY")
        assert ret.actor_id == "usr_scrutiny" and ret.reason.startswith("Lease document")
        assert ret.before_json["status"] == "IN_SCRUTINY" and ret.after_json["status"] == "RETURNED_FOR_DEFICIENCY"
        assert ret.request_id


def test_submitted_at_is_set_once_and_survives_resubmission(client, act, session_factory):
    with session_factory() as s:
        before = s.get(Application, "app_002").submitted_at
    assert act(INST_A, "app_002", "RESUBMIT", "Fixed").status_code == 200
    with session_factory() as s:
        assert s.get(Application, "app_002").submitted_at == before


def test_resubmission_returns_to_review_stage_and_records_actor_and_time(client, act, login):
    r = act(INST_A, "app_002", "RESUBMIT", "Signed lease attached.")
    assert r.json()["data"]["status"] == "RE_SCRUTINY"
    hist = client.get(f"{BASE}/app_002/history", headers=login(INST_A)).json()["data"]
    resub = next(h for h in hist if h["action"] == "RESUBMIT")
    assert resub["actor"]["id"] == "usr_institution_a" and resub["created_at"] and resub["reason"] == "Signed lease attached."
    routed = next(h for h in hist if h["action"] == "ROUTE_TO_RE_SCRUTINY")
    assert routed["reason"].startswith("Automatic routing") and routed["metadata"]["triggered_by_action"] == "RESUBMIT"


def test_different_templates_route_differently_after_scrutiny(act):
    assert act(SCRUTINY, "app_001", "COMPLETE_SCRUTINY").json()["data"]["status"] == "EVC_PENDING"  # NEW_INSTITUTION
    r = act(INST_A, "app_002", "RESUBMIT", "ok")                                                    # EXTENSION
    assert r.status_code == 200
    assert act(SCRUTINY, "app_002", "COMPLETE_SCRUTINY").json()["data"]["status"] == "AWAITING_AUTHORITY_DECISION"


# ------------------------------------------------------------------ invalid transitions

@pytest.mark.parametrize(
    "email,app_id,action",
    [
        (INST_A, "app_001", "SUBMIT"),                 # already submitted
        (SCRUTINY, "app_002", "COMPLETE_SCRUTINY"),    # returned cases must be resubmitted first
        (SCRUTINY, "app_001", "RECORD_APPROVAL"),      # cannot skip to a decision
        (INST_A, "app_005", "RESUBMIT"),               # draft cannot be resubmitted
        (INST_A, "app_002", "SUBMIT"),
        (COMMITTEE, "app_001", "FORWARD_TO_AUTHORITY"),  # NEW route, but committee stage not reached
    ],
)
def test_action_not_valid_from_current_stage_is_409(act, session_factory, email, app_id, action):
    with session_factory() as s:
        before = s.get(Application, app_id).status
    r = act(email, app_id, action, "reason")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    assert _status(session_factory, app_id) == before


def test_unknown_action_is_400(act):
    r = act(SCRUTINY, "app_001", "TELEPORT_TO_APPROVED")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_ACTION"
    assert act(SCRUTINY, "app_001", "   ").status_code == 422  # blank action fails schema validation


def test_action_is_case_insensitive_and_trimmed(act):
    assert act(SCRUTINY, "app_001", " complete_scrutiny ").status_code == 200


def test_extension_template_has_no_evc_step(act):
    # SCHEDULE_EVC is not part of the EXTENSION route at all -> unknown action (400), whoever asks
    r = act(SCRUTINY, "app_002", "SCHEDULE_EVC")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_ACTION"
    assert act(EVC, "app_002", "SCHEDULE_EVC").status_code == 400
    # in the NEW route the action exists but the case is not at the EVC stage yet -> 409
    assert act(EVC, "app_001", "SCHEDULE_EVC").status_code == 409


def test_terminal_cases_accept_no_further_actions(act, allowed, session_factory):
    assert act(INST_A, "app_005", "WITHDRAW", "Not needed.").json()["data"]["status"] == "WITHDRAWN"
    assert allowed(INST_A, "app_005") == {}
    for action in ("SUBMIT", "WITHDRAW", "RESUBMIT"):
        assert act(INST_A, "app_005", action, "x").status_code == 409


def test_system_routing_steps_cannot_be_invoked_by_clients(act, session_factory):
    with session_factory() as s:
        a = s.get(Application, "app_001")
        a.status, a.current_stage_id = "SUBMITTED", "stg_new_institution_submitted"
        s.commit()
    for email in (SCRUTINY, INST_A, ADMIN):
        r = act(email, "app_001", "ROUTE_TO_SCRUTINY")
        assert r.status_code == 403 and "automatically" in r.json()["error"]["message"], email
    assert _status(session_factory, "app_001") == "SUBMITTED"


# ------------------------------------------------------------------ required reasons

@pytest.mark.parametrize(
    "email,app_id,action",
    [
        (SCRUTINY, "app_001", "RETURN_FOR_DEFICIENCY"),
        (INST_A, "app_002", "RESUBMIT"),
        (INST_A, "app_002", "WITHDRAW"),
        (INST_A, "app_005", "WITHDRAW"),
    ],
)
@pytest.mark.parametrize("reason", [None, "", "   \n\t"])
def test_reason_required_actions_reject_missing_or_blank_reason(act, session_factory, email, app_id, action, reason):
    with session_factory() as s:
        before = s.get(Application, app_id).status
        n_hist = len(s.scalars(select(ApplicationStageHistory)).all())
        n_audit = len(s.scalars(select(AuditLog).where(AuditLog.action == "APPLICATION_TRANSITION")).all())
    r = act(email, app_id, action, reason)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"] == [{"field": "reason", "issue": "required"}]
    with session_factory() as s:  # nothing was written
        assert s.get(Application, app_id).status == before
        assert len(s.scalars(select(ApplicationStageHistory)).all()) == n_hist
        assert len(s.scalars(select(AuditLog).where(AuditLog.action == "APPLICATION_TRANSITION")).all()) == n_audit


def test_reason_not_required_for_complete_scrutiny_and_reason_is_trimmed(act, client, login):
    r = act(SCRUTINY, "app_001", "COMPLETE_SCRUTINY")
    assert r.status_code == 200
    r = act(INST_A, "app_002", "RESUBMIT", "   trimmed reason  ")
    assert r.status_code == 200
    hist = client.get(f"{BASE}/app_002/history", headers=login(INST_A)).json()["data"]
    assert next(h for h in hist if h["action"] == "RESUBMIT")["reason"] == "trimmed reason"


def test_reason_check_does_not_leak_to_unauthorised_roles(act):
    # a wrong-role caller gets 403 before the reason requirement is evaluated
    assert act(INST_A, "app_001", "RETURN_FOR_DEFICIENCY").status_code == 403


# ------------------------------------------------------------------ no direct status change

@pytest.mark.parametrize(
    "extra",
    [{"status": "APPROVED"}, {"to_stage": "APPROVED"}, {"current_stage_id": "x"}, {"assigned_to": "usr_admin"}, {"unknown": 1}],
)
def test_transition_body_cannot_carry_a_destination(act, session_factory, extra):
    r = act(SCRUTINY, "app_001", "COMPLETE_SCRUTINY", **extra)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _status(session_factory, "app_001") == "IN_SCRUTINY"


@pytest.mark.parametrize("method", ["put", "delete"])
def test_no_other_write_paths_for_status(client, login, session_factory, method):
    r = getattr(client, method)(f"{BASE}/app_001", headers=login(ADMIN), **({"json": {"status": "APPROVED"}} if method == "put" else {}))
    assert r.status_code == 405
    assert _status(session_factory, "app_001") == "IN_SCRUTINY"


def test_admin_and_management_cannot_make_decisions_or_move_cases(act, session_factory):
    for email in (ADMIN, MGMT):
        for action in ("COMPLETE_SCRUTINY", "RETURN_FOR_DEFICIENCY"):
            assert act(email, "app_001", action, "x").status_code == 403, (email, action)
    assert _status(session_factory, "app_001") == "IN_SCRUTINY"


# ------------------------------------------------------------------ role + assignment rules

def test_officer_assigned_to_someone_else_cannot_act(act, allowed, session_factory):
    with session_factory() as s:
        s.add(User(id="usr_scrutiny2", name="Scrutiny Officer 2", email="scrutiny2@example.test",
                   role="SCRUTINY_OFFICER", region_id="reg_central", is_active=True))
        s.commit()
    assert allowed("scrutiny2@example.test", "app_001") == {}
    r = act("scrutiny2@example.test", "app_001", "RETURN_FOR_DEFICIENCY", "x")
    assert r.status_code == 403 and "assigned to another officer" in r.json()["error"]["message"]
    assert _status(session_factory, "app_001") == "IN_SCRUTINY"
    assert act(SCRUTINY, "app_001", "RETURN_FOR_DEFICIENCY", "x").status_code == 200


def test_unassigned_queue_case_can_be_worked_by_a_scope_officer(act, session_factory):
    with session_factory() as s:
        s.get(Application, "app_001").assigned_to = None
        s.commit()
    assert act(SCRUTINY, "app_001", "COMPLETE_SCRUTINY").status_code == 200


def test_resubmission_prefers_the_officer_who_returned_the_case(act, session_factory):
    with session_factory() as s:
        s.add(User(id="usr_aaa_scrutiny", name="Earlier id officer", email="aaa@example.test",
                   role="SCRUTINY_OFFICER", region_id="reg_central", is_active=True))
        s.commit()
    # app_002 was returned by usr_scrutiny; usr_aaa_scrutiny sorts first and has zero load, yet continuity wins
    assert act(INST_A, "app_002", "RESUBMIT", "fixed").json()["data"]["assigned_to"] == "usr_scrutiny"


def test_new_cases_are_assigned_to_the_least_loaded_regional_officer(client, login, session_factory):
    with session_factory() as s:
        s.add(User(id="usr_aaa_scrutiny", name="Light load", email="aaa@example.test",
                   role="SCRUTINY_OFFICER", region_id="reg_central", is_active=True))
        s.commit()
    r = client.post(BASE, json={"category": "NEW_INSTITUTION", "submit": True}, headers=login(INST_A))
    assert r.json()["data"]["assigned_to"] == "usr_aaa_scrutiny"  # usr_scrutiny already holds app_001


def test_case_with_no_regional_officer_goes_to_unassigned_queue(client, login):
    r = client.post(BASE, json={"category": "NEW_INSTITUTION", "submit": True}, headers=login("institution.user.b@example.test"))
    d = r.json()["data"]  # inst_002 is in reg_west which has no scrutiny officer
    assert d["status"] == "IN_SCRUTINY" and d["assigned_to"] is None and d["responsible_roles"] == ["SCRUTINY_OFFICER"]


def test_evc_actions_are_managed_by_module_5(act, allowed, session_factory):
    assert allowed(EVC, "app_003") == {}  # not offered as a button...
    r = act(EVC, "app_003", "SCHEDULE_EVC")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTION_MANAGED_ELSEWHERE"  # ...and refused if forced
    assert _status(session_factory, "app_003") == "EVC_PENDING"


# ------------------------------------------------------------------ metadata handling

def test_metadata_reserved_keys_cannot_be_forged_and_size_is_limited(act, client, login):
    r = act(SCRUTINY, "app_001", "RETURN_FOR_DEFICIENCY", "x",
            {"checklist_code": "C1", "auto": True, "responds_to": "hist_fake", "transition_id": "forged"})
    assert r.status_code == 200
    hist = client.get(f"{BASE}/app_001/history", headers=login(SCRUTINY)).json()["data"]
    meta = next(h for h in hist if h["action"] == "RETURN_FOR_DEFICIENCY")["metadata"]
    assert meta["checklist_code"] == "C1" and "auto" not in meta and "responds_to" not in meta
    assert meta["transition_id"] == "wtr_new_institution_in_scrutiny_return_for_deficiency"
    big = act(SCRUTINY, "app_002", "COMPLETE_SCRUTINY", metadata={"blob": "x" * 5000})
    assert big.status_code == 422


def test_document_reference_must_belong_to_the_same_institution(act, session_factory):
    with session_factory() as s:
        s.add(Document(id="doc_other", institution_id="inst_003", document_type="LEASE", filename="x.pdf",
                       storage_key="synthetic/x.pdf", uploaded_by="usr_institution_a"))
        s.commit()
    r = act(INST_A, "app_002", "RESUBMIT", "fixed", {"document_ids": ["doc_other"]})
    assert r.status_code == 422 and _status(session_factory, "app_002") == "RETURNED_FOR_DEFICIENCY"


# ------------------------------------------------------------------ allowed-actions agrees with the engine

def test_allowed_actions_match_what_the_server_accepts(client, login, act, allowed, session_factory):
    expectations = {
        (SCRUTINY, "app_001"): {"COMPLETE_SCRUTINY", "RETURN_FOR_DEFICIENCY"},
        (INST_A, "app_001"): {"WITHDRAW"},
        (INST_A, "app_002"): {"RESUBMIT", "WITHDRAW"},
        (INST_A, "app_005"): {"SUBMIT", "WITHDRAW"},
        (SCRUTINY, "app_002"): set(),
        (REGIONAL, "app_001"): set(),
        (ADMIN, "app_001"): set(),
        (MGMT, "app_001"): set(),
        (EVC, "app_003"): set(),
    }
    for (email, app_id), expected in expectations.items():
        assert set(allowed(email, app_id)) == expected, (email, app_id)
    r = client.get(f"{BASE}/app_001/allowed-actions", headers=login(SCRUTINY)).json()["data"]
    assert r["application_id"] == "app_001" and r["status"] == "IN_SCRUTINY"
    item = next(a for a in r["actions"] if a["action"] == "COMPLETE_SCRUTINY")
    assert item == {"action": "COMPLETE_SCRUTINY", "label": "Mark scrutiny complete", "to_stage": "EVC_PENDING",
                    "to_stage_display_name": "EVC queue", "requires_reason": False}


@pytest.mark.parametrize(
    "email,app_id,action",
    [
        (SCRUTINY, "app_001", "COMPLETE_SCRUTINY"),
        (SCRUTINY, "app_001", "RETURN_FOR_DEFICIENCY"),
        (INST_A, "app_001", "WITHDRAW"),
        (INST_A, "app_002", "RESUBMIT"),
        (INST_A, "app_002", "WITHDRAW"),
        (INST_A, "app_005", "SUBMIT"),
        (INST_A, "app_005", "WITHDRAW"),
    ],
)
def test_every_offered_action_is_actually_accepted(allowed, act, email, app_id, action):
    """allowed-actions must never advertise a button the engine would refuse (fresh seeded DB per case)."""
    offered = allowed(email, app_id)
    assert action in offered
    r = act(email, app_id, action, "because" if offered[action]["requires_reason"] else None)
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ history

def test_history_is_paged_and_chronological(client, login):
    h = login(INST_A)
    r = client.get(f"{BASE}/app_002/history?page_size=2", headers=h)
    body = r.json()
    assert body["meta"]["total"] == 4 and len(body["data"]) == 2
    assert [e["action"] for e in body["data"]] == ["CREATE", "SUBMIT"]
    page2 = client.get(f"{BASE}/app_002/history?page_size=2&page=2", headers=h).json()["data"]
    assert [e["action"] for e in page2] == ["ROUTE_TO_SCRUTINY", "RETURN_FOR_DEFICIENCY"]
    assert page2[1]["reason"].startswith("Lease document") and page2[1]["actor"]["name"] == "Scrutiny Officer"
    assert page2[1]["from_stage"] == "IN_SCRUTINY" and page2[1]["to_stage"] == "RETURNED_FOR_DEFICIENCY"


def test_history_records_assignment_change(client, login, act):
    act(SCRUTINY, "app_001", "RETURN_FOR_DEFICIENCY", "x")
    ret = next(h for h in client.get(f"{BASE}/app_001/history", headers=login(SCRUTINY)).json()["data"]
               if h["action"] == "RETURN_FOR_DEFICIENCY")
    assert ret["metadata"]["assigned_to_before"] == "usr_scrutiny" and ret["metadata"]["assigned_to_after"] is None
