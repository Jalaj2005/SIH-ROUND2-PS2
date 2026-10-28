"""Workflow template configuration and engine-level behaviour (service layer, no HTTP)."""
from collections import deque

import pytest
from sqlalchemy import select

from app.core.enums import SYSTEM_ROLE, ApplicationStatus
from app.core.ids import utcnow
from app.models import Application, ApplicationStageHistory, AuditLog, User
from app.seed.demo_data import seed
from app.seed.workflow_templates import EXTENSION_OF_APPROVAL, NEW_INSTITUTION, TEMPLATES, validate_template
from app.services import workflow_service

SCR, EVC, COM = "usr_scrutiny", "usr_evc", "usr_committee"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.key)
def test_template_definitions_are_valid(template):
    validate_template(template)  # codes are ApplicationStatus values, one automatic step per stage, no dup (from, action)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.key)
def test_every_template_can_reach_approved_and_rejected(template):
    graph: dict[str, set[str]] = {}
    for t in template.transitions:
        graph.setdefault(t.from_stage, set()).add(t.to_stage)
    seen, queue = {"DRAFT"}, deque(["DRAFT"])
    while queue:
        for nxt in graph.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert {"APPROVED", "REJECTED", "CLOSED"} <= seen
    assert {s.code for s in template.stages} == seen  # every configured stage is reachable (no orphans)


def test_two_categories_follow_different_routes():
    new_codes = {s.code for s in NEW_INSTITUTION.stages}
    ext_codes = {s.code for s in EXTENSION_OF_APPROVAL.stages}
    assert {"EVC_PENDING", "EVC_SCHEDULED", "EVC_COMPLETED", "COMMITTEE_REVIEW"} <= new_codes
    assert not ({"EVC_PENDING", "COMMITTEE_REVIEW"} & ext_codes)
    scrutiny_done = {t.to_stage for t in NEW_INSTITUTION.transitions if t.action == "COMPLETE_SCRUTINY"}
    scrutiny_done_ext = {t.to_stage for t in EXTENSION_OF_APPROVAL.transitions if t.action == "COMPLETE_SCRUTINY"}
    assert scrutiny_done == {"EVC_PENDING"} and scrutiny_done_ext == {"AWAITING_AUTHORITY_DECISION"}


def test_no_user_role_can_trigger_automatic_steps():
    for t in TEMPLATES:
        for tr in t.transitions:
            if tr.role == SYSTEM_ROLE:
                assert tr.action.startswith("ROUTE_TO_")


def _user(db, uid):
    return db.get(User, uid)


def test_new_institution_route_with_evc_reaches_approved(db_session):
    """EVC steps are module-managed for clients, but the engine itself drives the whole NEW_INSTITUTION route."""
    db = db_session
    app = db.get(Application, "app_003")  # seeded at EVC_PENDING
    run = lambda user, action, reason=None, **kw: workflow_service.perform_transition(  # noqa: E731
        db, user=_user(db, user), application=app, action=action, reason=reason, **kw
    )
    run(EVC, "SCHEDULE_EVC", allow_managed=True)
    assert app.status == "EVC_SCHEDULED"
    run(EVC, "COMPLETE_EVC", allow_managed=True)
    assert app.status == "COMMITTEE_REVIEW"  # EVC_COMPLETED is auto-routed onward; completing EVC never approves
    run(COM, "FORWARD_TO_AUTHORITY")
    assert app.status == "AWAITING_AUTHORITY_DECISION"
    run(COM, "RECORD_APPROVAL", "Meets the prototype criteria.")
    db.commit()
    assert app.status == "APPROVED"

    actions = [h.action for h in db.scalars(
        select(ApplicationStageHistory).where(ApplicationStageHistory.application_id == "app_003")
        .order_by(ApplicationStageHistory.created_at))]
    assert actions[-5:] == ["SCHEDULE_EVC", "COMPLETE_EVC", "ROUTE_TO_COMMITTEE", "FORWARD_TO_AUTHORITY", "RECORD_APPROVAL"]


def test_current_stage_agrees_with_history_after_every_step(db_session):
    db = db_session
    app = db.get(Application, "app_001")
    scrutiny = _user(db, SCR)
    workflow_service.perform_transition(db, user=scrutiny, application=app, action="RETURN_FOR_DEFICIENCY", reason="x")
    db.commit()
    last = db.scalars(
        select(ApplicationStageHistory).where(ApplicationStageHistory.application_id == app.id)
        .order_by(ApplicationStageHistory.created_at.desc())
    ).first()
    stage = workflow_service.get_stage(db, app.workflow_template_id, app.status)
    assert last.to_stage == app.status == stage.stage_code and app.current_stage_id == stage.id


def test_stale_application_is_rejected_by_compare_and_swap(session_factory):
    """If the case moved between validation and write, the engine returns 409 instead of silently overwriting."""
    from app.core.errors import AppError

    with session_factory() as s1, session_factory() as s2:
        stale = s1.get(Application, "app_001")
        workflow_service.perform_transition(
            s2, user=s2.get(User, SCR), application=s2.get(Application, "app_001"),
            action="RETURN_FOR_DEFICIENCY", reason="first",
        )
        s2.commit()
        assert stale.status == "IN_SCRUTINY"  # s1 still holds the old state
        with pytest.raises(AppError) as exc:
            workflow_service.perform_transition(
                s1, user=s1.get(User, SCR), application=stale, action="COMPLETE_SCRUTINY"
            )
        assert exc.value.status_code == 409 and exc.value.code == "CONCURRENT_MODIFICATION"
        s1.rollback()
    with session_factory() as s:
        assert s.get(Application, "app_001").status == "RETURNED_FOR_DEFICIENCY"


def test_history_timestamps_are_strictly_increasing_within_one_request(db_session):
    db = db_session
    app = db.get(Application, "app_005")  # DRAFT
    workflow_service.perform_transition(db, user=_user(db, "usr_institution_a"), application=app, action="SUBMIT")
    db.commit()
    rows = db.scalars(select(ApplicationStageHistory).where(ApplicationStageHistory.application_id == "app_005")
                      .order_by(ApplicationStageHistory.created_at)).all()
    stamps = [r.created_at for r in rows]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    assert [r.action for r in rows][-2:] == ["SUBMIT", "ROUTE_TO_SCRUTINY"]
    assert app.status == "IN_SCRUTINY" and app.assigned_to == SCR and app.submitted_at is not None


def test_seed_does_not_rewind_cases_or_touch_history(db_session):
    db = db_session
    app = db.get(Application, "app_001")
    workflow_service.perform_transition(db, user=_user(db, SCR), application=app, action="RETURN_FOR_DEFICIENCY", reason="r")
    db.commit()
    n_hist = len(db.scalars(select(ApplicationStageHistory)).all())
    n_audit = len(db.scalars(select(AuditLog)).all())
    seed(db)
    seed(db)
    db.expire_all()
    assert db.get(Application, "app_001").status == "RETURNED_FOR_DEFICIENCY"
    assert len(db.scalars(select(ApplicationStageHistory)).all()) == n_hist
    assert len(db.scalars(select(AuditLog)).all()) == n_audit
    assert len(db.scalars(select(Application)).all()) == 5
