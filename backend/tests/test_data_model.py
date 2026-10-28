import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppendOnlyViolation
from app.core.ids import utcnow
from app.models import ApplicationStageHistory, Institution, Notification, User
from app.seed.demo_data import seed
from app.services.audit_service import log_event

EXPECTED_TABLES = {
    "users", "institutions", "applications", "workflow_templates", "workflow_stages",
    "workflow_transitions", "application_stage_history", "compliance_items", "documents",
    "evc_records", "notifications", "escalations", "audit_logs", "workflow_rules",
}


def test_all_shared_tables_exist(engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_seed_is_idempotent(db_session):
    def counts():
        return (
            db_session.scalar(select(func.count()).select_from(User)),
            db_session.scalar(select(func.count()).select_from(Institution)),
        )

    before = counts()
    seed(db_session)
    seed(db_session)
    assert counts() == before == (9, 3)


def test_timestamps_roundtrip_as_utc(db_session):
    log = log_event(db_session, action="T", entity_type="t", entity_id="1")
    db_session.commit()
    assert log.timestamp.tzinfo is not None
    db_session.expire_all()
    assert db_session.get(type(log), log.id).timestamp.utcoffset().total_seconds() == 0


def test_audit_log_is_append_only(db_session):
    log = log_event(
        db_session, action="X", entity_type="t", entity_id="1", before={"a": 1}, after={"a": 2}, reason="why"
    )
    db_session.commit()
    assert log.before_json == {"a": 1} and log.after_json == {"a": 2}

    log.reason = "tampered"
    with pytest.raises(AppendOnlyViolation):
        db_session.commit()
    db_session.rollback()

    db_session.delete(log)
    with pytest.raises(AppendOnlyViolation):
        db_session.commit()
    db_session.rollback()


def test_stage_history_is_append_only(db_session):
    from app.models import Application, WorkflowTemplate

    db_session.add(WorkflowTemplate(id="wft_t", name="T", category="NEW"))
    db_session.flush()
    db_session.add(
        Application(id="app_t", application_number="N-1", institution_id="inst_001", category="NEW",
                    workflow_template_id="wft_t", status="SUBMITTED")
    )
    db_session.flush()
    row = ApplicationStageHistory(application_id="app_t", to_stage="SUBMITTED", action="SUBMIT", actor_id="usr_institution_a")
    db_session.add(row)
    db_session.commit()
    row.reason = "edit"
    with pytest.raises(AppendOnlyViolation):
        db_session.commit()
    db_session.rollback()


def _notification(status: str, key: str = "k1") -> Notification:
    return Notification(
        recipient_id="usr_admin", entity_type="COMPLIANCE_ITEM", entity_id="comp_1", rule_code="OVERDUE_3D",
        message="m", severity="WARNING", dedupe_key=key, status=status, created_at=utcnow(),
    )


def test_only_one_active_notification_per_dedupe_key(db_session):
    db_session.add(_notification("ACTIVE"))
    db_session.commit()

    db_session.add(_notification("ACTIVE"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(_notification("ACTIVE", key="k2"))  # different key is fine
    db_session.add(_notification("READ"))              # inactive duplicates are fine
    db_session.commit()


def test_foreign_keys_are_enforced(db_session):
    db_session.add(User(id="u_bad", name="n", email="bad@example.test", role="INSTITUTION_USER", institution_id="inst_missing"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
