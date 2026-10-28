from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.core.pagination import PageParams, pagination_params
from app.models.identity import User
from app.models.workflow import WorkflowStage, WorkflowTemplate, WorkflowTransition
from app.schemas.application import ApplicationDetailOut, TransitionRequest
from app.schemas.common import Envelope, ListEnvelope, paged, single
from app.schemas.workflow import AllowedActionsOut, HistoryEntryOut, WorkflowTemplateOut
from app.services import application_service, workflow_service

router = APIRouter(tags=["Workflow"])


@router.get("/workflow-templates", response_model=ListEnvelope[WorkflowTemplateOut], summary="Configured workflow templates")
def list_workflow_templates(
    request: Request,
    params: PageParams = Depends(pagination_params),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = db.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.category, WorkflowTemplate.version.desc())).all()
    total = len(templates)
    page = templates[params.offset : params.offset + params.page_size]
    out = []
    for t in page:
        stages = db.scalars(select(WorkflowStage).where(WorkflowStage.template_id == t.id).order_by(WorkflowStage.sequence)).all()
        transitions = db.scalars(
            select(WorkflowTransition).where(WorkflowTransition.template_id == t.id)
            .order_by(WorkflowTransition.from_stage, WorkflowTransition.action)
        ).all()
        out.append(
            {
                "id": t.id, "name": t.name, "category": t.category, "version": t.version, "is_active": t.is_active,
                "stages": [
                    {"stage_code": s.stage_code, "display_name": s.display_name, "sequence": s.sequence,
                     "allowed_roles": s.allowed_roles or [], "default_sla_hours": s.default_sla_hours}
                    for s in stages
                ],
                "transitions": [
                    {"from_stage": x.from_stage, "action": x.action, "to_stage": x.to_stage,
                     "required_role": x.required_role, "requires_reason": x.requires_reason}
                    for x in transitions
                ],
            }
        )
    return paged(out, request_id=get_request_id(request), page=params.page, page_size=params.page_size, total=total)


@router.get(
    "/applications/{application_id}/history", response_model=ListEnvelope[HistoryEntryOut],
    summary="Chronological stage history and relevant audit events",
)
def application_history(
    application_id: str,
    request: Request,
    params: PageParams = Depends(pagination_params),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = workflow_service.get_application_for_user(db, user, application_id)
    entries = workflow_service.get_history(db, application)
    return paged(
        entries[params.offset : params.offset + params.page_size],
        request_id=get_request_id(request), page=params.page, page_size=params.page_size, total=len(entries),
    )


@router.get(
    "/applications/{application_id}/allowed-actions", response_model=Envelope[AllowedActionsOut],
    summary="Actions the current user may take on this case now",
)
def allowed_actions(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = workflow_service.get_application_for_user(db, user, application_id)
    data = {
        "application_id": application.id,
        "status": application.status,
        "actions": workflow_service.list_allowed_actions(db, user, application),
    }
    return single(data, get_request_id(request))


@router.post(
    "/applications/{application_id}/transitions", response_model=Envelope[ApplicationDetailOut],
    summary="Apply a workflow action (validated server-side; the only way status/stage change)",
)
def transition_application(
    application_id: str,
    payload: TransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    request_id = get_request_id(request)
    application = workflow_service.get_application_for_user(db, user, application_id)
    workflow_service.perform_transition(
        db, user=user, application=application, action=payload.action, reason=payload.reason,
        metadata=payload.metadata, request_id=request_id,
    )
    db.commit()
    db.refresh(application)
    return single(application_service.serialize_detail(db, application), request_id)
