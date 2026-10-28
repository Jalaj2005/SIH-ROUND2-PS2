"""Workflow engine (Module 1).

Single entry point for changing an application's status/stage: `perform_transition`.
Nothing else (no PATCH, no other module) may write applications.status / current_stage_id.

Check order for a client transition (documented in docs/api-contract.md):
  401 unauthenticated -> 404 missing / 403 out of scope or someone else's draft
  -> 400 INVALID_ACTION (action unknown to this template)
  -> 409 INVALID_TRANSITION (action exists but not from the current stage)
  -> 403 role not permitted / system-only step
  -> 409 ACTION_MANAGED_ELSEWHERE (EVC steps belong to Module 5)
  -> 403 case assigned to another officer
  -> 422 reason required / bad document references
  -> apply (compare-and-swap; 409 CONCURRENT_MODIFICATION if the case moved meanwhile)

All writes (status change, history row, audit row) are staged on the caller's session; the router commits once.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.core.enums import (
    SYSTEM_ROLE,
    ApplicationStatus,
    Role,
    WorkflowAction,
)
from app.core.errors import AppError, conflict, forbidden, not_found
from app.core.ids import utcnow
from app.core.permissions import can_access_institution, institution_id_in_scope, parse_role
from app.models.compliance import Document
from app.models.identity import Institution, User
from app.models.workflow import (
    Application,
    ApplicationStageHistory,
    WorkflowStage,
    WorkflowTemplate,
    WorkflowTransition,
)
from app.services import audit_service

MAX_AUTO_STEPS = 5
# EVC steps are driven by Module 5 (which also writes evc_records); the public endpoint refuses them so the
# application status can never drift from the EVC record. Module 5 calls perform_transition(allow_managed=True).
MANAGED_ACTIONS = frozenset({WorkflowAction.SCHEDULE_EVC.value, WorkflowAction.COMPLETE_EVC.value})
ASSIGNABLE_ROLES = (Role.SCRUTINY_OFFICER,)
ASSIGNMENT_ENFORCED_ROLES = frozenset({Role.SCRUTINY_OFFICER})
ACTIVE_REVIEW_STATUSES = (ApplicationStatus.IN_SCRUTINY.value, ApplicationStatus.RE_SCRUTINY.value)
RESERVED_META_KEYS = frozenset(
    {"transition_id", "assigned_to_before", "assigned_to_after", "auto", "triggered_by_action", "responds_to"}
)

ACTION_LABELS = {
    "SUBMIT": "Submit application",
    "RETURN_FOR_DEFICIENCY": "Return for deficiency",
    "RESUBMIT": "Resubmit with corrections",
    "COMPLETE_SCRUTINY": "Mark scrutiny complete",
    "FORWARD_TO_AUTHORITY": "Forward to competent authority",
    "RECORD_APPROVAL": "Record approval decision",
    "RECORD_REJECTION": "Record rejection decision",
    "CLOSE": "Close case",
    "WITHDRAW": "Withdraw application",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " ").capitalize())


# ------------------------------------------------------------------ access

def application_scope_clause(user: User):
    """Institution/region scope (Module 0) plus: drafts are visible only to institution users."""
    clause = institution_id_in_scope(user, Application.institution_id)
    if parse_role(user) != Role.INSTITUTION_USER:
        clause = and_(clause, Application.status != ApplicationStatus.DRAFT.value)
    return clause


def get_application_for_user(db: Session, user: User, application_id: str) -> Application:
    """404 if missing, 403 if outside the caller's scope (same convention as institutions)."""
    application = db.get(Application, application_id)
    if application is None:
        raise not_found("Application not found.")
    if not can_access_institution(db, user, application.institution_id):
        raise forbidden("This record is outside your authorised scope.")
    if application.status == ApplicationStatus.DRAFT.value and parse_role(user) != Role.INSTITUTION_USER:
        raise forbidden("Draft applications are visible only to the submitting institution.")
    return application


def _assignment_ok(user: User, application: Application) -> bool:
    role = parse_role(user)
    if role in ASSIGNMENT_ENFORCED_ROLES:
        return application.assigned_to in (None, user.id)
    return True


# ------------------------------------------------------------------ templates

def resolve_template(db: Session, category: str) -> WorkflowTemplate:
    template = db.scalar(
        select(WorkflowTemplate)
        .where(WorkflowTemplate.category == category, WorkflowTemplate.is_active.is_(True))
        .order_by(WorkflowTemplate.version.desc())
        .limit(1)
    )
    if template is None:
        raise AppError(
            "VALIDATION_ERROR",
            f"No active workflow template for category '{category}'.",
            422,
            details=[{"field": "category", "issue": "unknown category"}],
        )
    return template


def get_stage(db: Session, template_id: str, stage_code: str) -> WorkflowStage | None:
    return db.scalar(
        select(WorkflowStage).where(WorkflowStage.template_id == template_id, WorkflowStage.stage_code == stage_code)
    )


# ------------------------------------------------------------------ allowed actions

def list_allowed_actions(db: Session, user: User, application: Application) -> list[dict[str, Any]]:
    """Actions the *current user* may take now. Mirrors perform_transition's checks so UI buttons never lie."""
    role = parse_role(user)
    if role is None or not _assignment_ok(user, application):
        return []
    rows = db.scalars(
        select(WorkflowTransition)
        .where(
            WorkflowTransition.template_id == application.workflow_template_id,
            WorkflowTransition.from_stage == application.status,
            WorkflowTransition.required_role == role.value,
        )
        .order_by(WorkflowTransition.action)
    ).all()
    names = {
        s.stage_code: s.display_name
        for s in db.scalars(select(WorkflowStage).where(WorkflowStage.template_id == application.workflow_template_id))
    }
    return [
        {
            "action": t.action,
            "label": action_label(t.action),
            "to_stage": t.to_stage,
            "to_stage_display_name": names.get(t.to_stage),
            "requires_reason": t.requires_reason,
        }
        for t in rows
        if t.action not in MANAGED_ACTIONS
    ]


# ------------------------------------------------------------------ transitions

class _Clock:
    """Strictly increasing timestamps so history order is deterministic even on coarse clocks."""

    def __init__(self, last: datetime | None):
        self.last = last

    def tick(self) -> datetime:
        now = utcnow()
        if self.last is not None and now <= self.last:
            now = self.last + timedelta(microseconds=1)
        self.last = now
        return now


def _snapshot(application: Application) -> dict[str, Any]:
    return {
        "status": application.status,
        "current_stage_id": application.current_stage_id,
        "assigned_to": application.assigned_to,
    }


def _find_transition(db: Session, template_id: str, from_stage: str, action: str) -> WorkflowTransition | None:
    return db.scalar(
        select(WorkflowTransition).where(
            WorkflowTransition.template_id == template_id,
            WorkflowTransition.from_stage == from_stage,
            WorkflowTransition.action == action,
        )
    )


def _action_exists(db: Session, template_id: str, action: str) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(WorkflowTransition)
            .where(WorkflowTransition.template_id == template_id, WorkflowTransition.action == action)
        )
        or 0
    ) > 0


def _validate_metadata(db: Session, application: Application, metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = {k: v for k, v in (metadata or {}).items() if k not in RESERVED_META_KEYS}
    ids = meta.get("document_ids")
    if ids is not None:
        if not isinstance(ids, list) or len(ids) > 20 or not all(isinstance(i, str) and i for i in ids):
            raise AppError(
                "VALIDATION_ERROR", "document_ids must be a list of up to 20 document ids.", 422,
                details=[{"field": "metadata.document_ids", "issue": "invalid"}],
            )
        found = {
            d.id
            for d in db.scalars(
                select(Document).where(
                    Document.id.in_(ids),
                    Document.institution_id == application.institution_id,
                    (Document.application_id.is_(None)) | (Document.application_id == application.id),
                )
            )
        }
        missing = sorted(set(ids) - found)
        if missing:
            raise AppError(
                "VALIDATION_ERROR", "Some referenced documents do not exist for this application.", 422,
                details=[{"field": "metadata.document_ids", "issue": f"unknown or inaccessible: {', '.join(missing)}"}],
            )
    return meta


def _choose_assignee(db: Session, application: Application, stage: WorkflowStage) -> str | None:
    """Scrutiny stages get an officer from the institution's region: the officer who last returned the case
    (continuity), otherwise the one with the fewest active cases (ties by id). No candidate => unassigned queue."""
    role = next((r for r in ASSIGNABLE_ROLES if r.value in (stage.allowed_roles or [])), None)
    if role is None:
        return None
    institution = db.get(Institution, application.institution_id)
    candidates = db.scalars(
        select(User.id)
        .where(User.is_active.is_(True), User.role == role.value, User.region_id == institution.region_id)
        .order_by(User.id)
    ).all()
    if not candidates:
        return None
    last_returner = db.scalar(
        select(ApplicationStageHistory.actor_id)
        .where(
            ApplicationStageHistory.application_id == application.id,
            ApplicationStageHistory.action == WorkflowAction.RETURN_FOR_DEFICIENCY.value,
        )
        .order_by(ApplicationStageHistory.created_at.desc())
        .limit(1)
    )
    if last_returner in candidates:
        return last_returner
    load = dict(
        db.execute(
            select(Application.assigned_to, func.count())
            .where(Application.assigned_to.in_(candidates), Application.status.in_(ACTIVE_REVIEW_STATUSES))
            .group_by(Application.assigned_to)
        ).all()
    )
    return min(candidates, key=lambda uid: (load.get(uid, 0), uid))


def _apply_step(
    db: Session,
    application: Application,
    transition: WorkflowTransition,
    actor: User,
    *,
    reason: str | None,
    client_meta: dict[str, Any],
    request_id: str | None,
    clock: _Clock,
    auto: bool,
    triggered_by: str | None = None,
) -> None:
    to_stage = get_stage(db, application.workflow_template_id, transition.to_stage)
    if to_stage is None or transition.to_stage not in {s.value for s in ApplicationStatus}:
        raise AppError("WORKFLOW_CONFIG_ERROR", "The workflow template is misconfigured.", 500)

    before = _snapshot(application)
    new_assignee = _choose_assignee(db, application, to_stage)
    ts = clock.tick()
    values: dict[str, Any] = {
        "status": to_stage.stage_code,
        "current_stage_id": to_stage.id,
        "assigned_to": new_assignee,
        "updated_at": ts,
    }
    if transition.action == WorkflowAction.SUBMIT.value and application.submitted_at is None:
        values["submitted_at"] = ts

    # Compare-and-swap on the stage we validated against: a concurrent transition makes this a clean 409.
    result = db.execute(
        update(Application)
        .where(Application.id == application.id, Application.status == transition.from_stage)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise conflict("The application was changed by another action. Reload and try again.", "CONCURRENT_MODIFICATION")

    meta: dict[str, Any] = {
        **client_meta,
        "transition_id": transition.id,
        "assigned_to_before": before["assigned_to"],
        "assigned_to_after": new_assignee,
    }
    if auto:
        meta.update(auto=True, triggered_by_action=triggered_by)
        reason = f"Automatic routing {transition.from_stage} -> {transition.to_stage} (workflow rule {transition.id})"
    if transition.action == WorkflowAction.RESUBMIT.value:
        meta["responds_to"] = db.scalar(
            select(ApplicationStageHistory.id)
            .where(
                ApplicationStageHistory.application_id == application.id,
                ApplicationStageHistory.action == WorkflowAction.RETURN_FOR_DEFICIENCY.value,
            )
            .order_by(ApplicationStageHistory.created_at.desc())
            .limit(1)
        )

    db.add(
        ApplicationStageHistory(
            application_id=application.id,
            from_stage=transition.from_stage,
            to_stage=transition.to_stage,
            action=transition.action,
            reason=reason,
            actor_id=actor.id,
            created_at=ts,
            metadata_json=meta,
        )
    )
    db.refresh(application)
    audit_service.log_event(
        db,
        action="APPLICATION_TRANSITION",
        entity_type="application",
        entity_id=application.id,
        actor_id=actor.id,
        reason=reason,
        before=before,
        after={**_snapshot(application), "workflow_action": transition.action, "auto": auto},
        request_id=request_id,
    )


def _last_history_ts(db: Session, application_id: str) -> datetime | None:
    return db.scalar(
        select(func.max(ApplicationStageHistory.created_at)).where(ApplicationStageHistory.application_id == application_id)
    )


def perform_transition(
    db: Session,
    *,
    user: User,
    application: Application,
    action: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
    allow_managed: bool = False,
) -> Application:
    """Validate and apply one user action, then any automatic routing steps that follow it. Does not commit."""
    action = (action or "").strip().upper()
    template_id = application.workflow_template_id
    transition = _find_transition(db, template_id, application.status, action)

    if transition is None:
        if _action_exists(db, template_id, action):
            raise conflict(
                f"Action {action} is not allowed while the application is in stage {application.status}.",
                "INVALID_TRANSITION",
            )
        raise AppError("INVALID_ACTION", f"Unknown action '{action}' for this application's workflow.", 400)

    role = parse_role(user)
    if transition.required_role == SYSTEM_ROLE:
        raise forbidden("This step is performed automatically by the workflow engine and cannot be invoked.")
    if role is None or role.value != transition.required_role:
        raise forbidden(f"Your role is not permitted to perform {action}.")
    if action in MANAGED_ACTIONS and not allow_managed:
        raise conflict(
            f"{action} is recorded through the EVC endpoints, not the generic transition endpoint.",
            "ACTION_MANAGED_ELSEWHERE",
        )
    if not _assignment_ok(user, application):
        raise forbidden("This case is assigned to another officer.")

    reason = (reason or "").strip() or None
    if transition.requires_reason and reason is None:
        raise AppError(
            "VALIDATION_ERROR", "A reason is required for this action.", 422,
            details=[{"field": "reason", "issue": "required"}],
        )
    client_meta = _validate_metadata(db, application, metadata)

    clock = _Clock(_last_history_ts(db, application.id))
    _apply_step(
        db, application, transition, user,
        reason=reason, client_meta=client_meta, request_id=request_id, clock=clock, auto=False,
    )

    for _ in range(MAX_AUTO_STEPS):  # automatic routing (e.g. SUBMITTED -> IN_SCRUTINY)
        auto_step = db.scalar(
            select(WorkflowTransition).where(
                WorkflowTransition.template_id == template_id,
                WorkflowTransition.from_stage == application.status,
                WorkflowTransition.required_role == SYSTEM_ROLE,
            )
        )
        if auto_step is None:
            break
        _apply_step(
            db, application, auto_step, user,
            reason=None, client_meta={}, request_id=request_id, clock=clock, auto=True, triggered_by=action,
        )
    else:  # pragma: no cover - guards against a cyclic SYSTEM map
        raise AppError("WORKFLOW_CONFIG_ERROR", "Automatic routing did not terminate.", 500)
    return application


# ------------------------------------------------------------------ history

def get_history(db: Session, application: Application) -> list[dict[str, Any]]:
    """Chronological stage history plus audit events for this application that are not already stage rows."""
    stage_rows = db.scalars(
        select(ApplicationStageHistory).where(ApplicationStageHistory.application_id == application.id)
    ).all()
    from app.models.ops import AuditLog  # local import: ops model is only needed here

    audit_rows = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "application",
            AuditLog.entity_id == application.id,
            AuditLog.action.not_in(["APPLICATION_TRANSITION", "APPLICATION_CREATED"]),
        )
    ).all()
    actor_ids = {r.actor_id for r in stage_rows} | {r.actor_id for r in audit_rows if r.actor_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids)))} if actor_ids else {}

    def actor(uid: str | None):
        u = users.get(uid) if uid else None
        return {"id": u.id, "name": u.name, "role": u.role} if u else ({"id": uid, "name": uid} if uid else None)

    entries = [
        {
            "id": r.id, "entry_type": "STAGE_TRANSITION", "action": r.action, "from_stage": r.from_stage,
            "to_stage": r.to_stage, "reason": r.reason, "actor": actor(r.actor_id), "created_at": r.created_at,
            "metadata": r.metadata_json,
        }
        for r in stage_rows
    ] + [
        {
            "id": r.id, "entry_type": "AUDIT_EVENT", "action": r.action, "from_stage": None, "to_stage": None,
            "reason": r.reason, "actor": actor(r.actor_id), "created_at": r.timestamp,
            "metadata": {"before": r.before_json, "after": r.after_json},
        }
        for r in audit_rows
    ]
    entries.sort(key=lambda e: (e["created_at"], e["id"]))
    return entries
