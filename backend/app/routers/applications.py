from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id, require_roles
from app.core.enums import Role
from app.core.pagination import PageParams, paginate, pagination_params
from app.models.identity import Institution, User
from app.models.workflow import Application, WorkflowStage
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationUpdate,
)
from app.schemas.common import Envelope, ListEnvelope, paged, single
from app.services import application_service, workflow_service

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.get("", response_model=ListEnvelope[ApplicationOut], summary="Paged, filterable application list (scoped)")
def list_applications(
    request: Request,
    status_filter: str | None = Query(None, alias="status", description="Exact status, e.g. IN_SCRUTINY"),
    institution_id: str | None = Query(None, description="Narrow to one institution (still limited to your scope)"),
    stage: str | None = Query(None, description="Current stage_code"),
    assigned_to: str | None = Query(None, description="User id, or 'me'"),
    category: str | None = Query(None),
    q: str | None = Query(None, max_length=100, description="Search application number or institution name"),
    params: PageParams = Depends(pagination_params),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Application).where(workflow_service.application_scope_clause(user))
    if status_filter:
        stmt = stmt.where(Application.status == status_filter.strip().upper())
    if institution_id:
        stmt = stmt.where(Application.institution_id == institution_id)
    if stage:
        stmt = stmt.where(
            Application.current_stage_id.in_(
                select(WorkflowStage.id).where(WorkflowStage.stage_code == stage.strip().upper())
            )
        )
    if assigned_to:
        stmt = stmt.where(Application.assigned_to == (user.id if assigned_to == "me" else assigned_to))
    if category:
        stmt = stmt.where(Application.category == category.strip().upper())
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(
            Application.application_number.icontains(term, autoescape=True)
            | Application.institution_id.in_(select(Institution.id).where(Institution.name.icontains(term, autoescape=True)))
        )
    stmt = stmt.order_by(Application.updated_at.desc(), Application.id)
    items, total = paginate(db, stmt, params)
    return paged(
        application_service.serialize_applications(db, items),
        request_id=get_request_id(request), page=params.page, page_size=params.page_size, total=total,
    )


@router.post(
    "", status_code=201, response_model=Envelope[ApplicationDetailOut],
    summary="Create a DRAFT (or create and submit) application — institution users only",
)
def create_application(
    payload: ApplicationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.INSTITUTION_USER)),
):
    request_id = get_request_id(request)
    application = application_service.create_application(
        db, user=user, category=payload.category, institution_id=payload.institution_id,
        submit=payload.submit, request_id=request_id,
    )
    db.commit()
    db.refresh(application)
    return single(application_service.serialize_detail(db, application), request_id)


@router.get("/{application_id}", response_model=Envelope[ApplicationDetailOut], summary="Application detail")
def get_application(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = workflow_service.get_application_for_user(db, user, application_id)
    return single(application_service.serialize_detail(db, application), get_request_id(request))


@router.patch(
    "/{application_id}", response_model=Envelope[ApplicationDetailOut],
    summary="Edit allowed fields only (never status/stage — use /transitions)",
)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.INSTITUTION_USER)),
):
    request_id = get_request_id(request)
    application = workflow_service.get_application_for_user(db, user, application_id)
    application_service.update_editable_fields(
        db, user=user, application=application, changes=payload.model_dump(exclude_none=True), request_id=request_id
    )
    db.commit()
    db.refresh(application)
    return single(application_service.serialize_detail(db, application), request_id)
