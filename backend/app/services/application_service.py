"""Application create/edit/read helpers (Module 1). Status and stage are never written here except for the
initial DRAFT placement; every later change goes through workflow_service.perform_transition."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus, WorkflowAction
from app.core.errors import AppError, conflict, forbidden
from app.core.ids import utcnow
from app.models.identity import Institution, User
from app.models.workflow import Application, ApplicationStageHistory, WorkflowStage, WorkflowTemplate
from app.services import audit_service, workflow_service


def _new_application_number(db: Session) -> str:
    for _ in range(5):
        number = f"APP-{utcnow().year}-{uuid.uuid4().hex[:6].upper()}"
        if db.scalar(select(Application.id).where(Application.application_number == number)) is None:
            return number
    raise AppError("INTERNAL_ERROR", "Could not allocate an application number.", 500)  # pragma: no cover


def create_application(
    db: Session, *, user: User, category: str, institution_id: str | None, submit: bool, request_id: str | None
) -> Application:
    if not user.institution_id:
        raise forbidden("Your account is not linked to an institution.")
    if institution_id is not None and institution_id != user.institution_id:
        raise forbidden("You can only create applications for your own institution.")

    template = workflow_service.resolve_template(db, category)
    draft_stage = workflow_service.get_stage(db, template.id, ApplicationStatus.DRAFT.value)
    if draft_stage is None:
        raise AppError("WORKFLOW_CONFIG_ERROR", "The workflow template has no DRAFT stage.", 500)

    now = utcnow()
    application = Application(
        application_number=_new_application_number(db),
        institution_id=user.institution_id,
        category=template.category,
        workflow_template_id=template.id,
        status=ApplicationStatus.DRAFT.value,
        current_stage_id=draft_stage.id,
        assigned_to=None,
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    db.flush()
    db.add(
        ApplicationStageHistory(
            application_id=application.id, from_stage=None, to_stage=ApplicationStatus.DRAFT.value,
            action=WorkflowAction.CREATE.value, reason=None, actor_id=user.id, created_at=now,
            metadata_json={"template_id": template.id, "template_version": template.version},
        )
    )
    audit_service.log_event(
        db, action="APPLICATION_CREATED", entity_type="application", entity_id=application.id,
        actor_id=user.id, after={"application_number": application.application_number, "category": application.category,
                                 "status": application.status}, request_id=request_id,
    )
    if submit:
        workflow_service.perform_transition(
            db, user=user, application=application, action=WorkflowAction.SUBMIT.value, request_id=request_id
        )
    return application


def update_editable_fields(
    db: Session, *, user: User, application: Application, changes: dict[str, Any], request_id: str | None
) -> Application:
    """Only `category`, only while DRAFT, only by the owning institution's user. Changing the category re-selects
    the workflow template (still at DRAFT), i.e. the server derives the stage; the client never sets it."""
    if user.institution_id != application.institution_id:
        raise forbidden("Only the owning institution can edit this application.")
    if application.status != ApplicationStatus.DRAFT.value:
        raise conflict("Only DRAFT applications can be edited.", "APPLICATION_NOT_EDITABLE")
    if not changes:
        raise AppError(
            "VALIDATION_ERROR", "No editable fields supplied.", 422, details=[{"field": None, "issue": "nothing to update"}]
        )

    before = {"category": application.category, "workflow_template_id": application.workflow_template_id}
    category = changes.get("category")
    if category and category != application.category:
        template = workflow_service.resolve_template(db, category)
        draft_stage = workflow_service.get_stage(db, template.id, ApplicationStatus.DRAFT.value)
        if draft_stage is None:
            raise AppError("WORKFLOW_CONFIG_ERROR", "The workflow template has no DRAFT stage.", 500)
        application.category = template.category
        application.workflow_template_id = template.id
        application.current_stage_id = draft_stage.id
    after = {"category": application.category, "workflow_template_id": application.workflow_template_id}
    if after != before:
        application.updated_at = utcnow()
        audit_service.log_event(
            db, action="APPLICATION_UPDATED", entity_type="application", entity_id=application.id,
            actor_id=user.id, before=before, after=after, request_id=request_id,
        )
    return application


# ------------------------------------------------------------------ serialization (bulk, no N+1)

def _stage_entered_map(db: Session, ids: Sequence[str]) -> dict[str, Any]:
    if not ids:
        return {}
    rows = db.execute(
        select(ApplicationStageHistory.application_id, func.max(ApplicationStageHistory.created_at))
        .where(ApplicationStageHistory.application_id.in_(ids))
        .group_by(ApplicationStageHistory.application_id)
    ).all()
    return dict(rows)


def serialize_applications(db: Session, apps: Sequence[Application]) -> list[dict[str, Any]]:
    if not apps:
        return []
    inst = {i.id: i for i in db.scalars(select(Institution).where(Institution.id.in_({a.institution_id for a in apps})))}
    tmpl = {t.id: t for t in db.scalars(select(WorkflowTemplate).where(WorkflowTemplate.id.in_({a.workflow_template_id for a in apps})))}
    stage_ids = {a.current_stage_id for a in apps if a.current_stage_id}
    stages = {s.id: s for s in db.scalars(select(WorkflowStage).where(WorkflowStage.id.in_(stage_ids)))} if stage_ids else {}
    assignee_ids = {a.assigned_to for a in apps if a.assigned_to}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(assignee_ids)))} if assignee_ids else {}
    entered = _stage_entered_map(db, [a.id for a in apps])

    out = []
    for a in apps:
        stage = stages.get(a.current_stage_id)
        entered_at = entered.get(a.id)
        due = entered_at + timedelta(hours=stage.default_sla_hours) if (stage and stage.default_sla_hours and entered_at) else None
        out.append(
            {
                "id": a.id,
                "application_number": a.application_number,
                "institution_id": a.institution_id,
                "institution_name": inst[a.institution_id].name if a.institution_id in inst else None,
                "category": a.category,
                "workflow_template_id": a.workflow_template_id,
                "workflow_template_name": tmpl[a.workflow_template_id].name if a.workflow_template_id in tmpl else None,
                "status": a.status,
                "current_stage": stage,
                "responsible_roles": [r for r in (stage.allowed_roles if stage else []) if r != "SYSTEM"],
                "assigned_to": a.assigned_to,
                "assigned_to_name": users[a.assigned_to].name if a.assigned_to in users else None,
                "submitted_at": a.submitted_at,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "stage_entered_at": entered_at,
                "stage_due_at": due,
            }
        )
    return out


def serialize_detail(db: Session, application: Application) -> dict[str, Any]:
    data = serialize_applications(db, [application])[0]
    data["open_deficiency"] = None
    if application.status == ApplicationStatus.RETURNED_FOR_DEFICIENCY.value:
        row = db.scalars(
            select(ApplicationStageHistory)
            .where(
                ApplicationStageHistory.application_id == application.id,
                ApplicationStageHistory.action == WorkflowAction.RETURN_FOR_DEFICIENCY.value,
            )
            .order_by(ApplicationStageHistory.created_at.desc())
            .limit(1)
        ).first()
        if row is not None:
            actor = db.get(User, row.actor_id)
            data["open_deficiency"] = {
                "history_id": row.id,
                "reason": row.reason,
                "returned_at": row.created_at,
                "returned_by": {"id": actor.id, "name": actor.name, "role": actor.role} if actor else None,
                "checklist_code": (row.metadata_json or {}).get("checklist_code"),
            }
    return data
