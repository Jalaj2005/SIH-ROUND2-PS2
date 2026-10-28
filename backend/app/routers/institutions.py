from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.core.pagination import PageParams, paginate, pagination_params
from app.core.permissions import get_institution_in_scope, institution_scope_clause
from app.models.identity import Institution, User
from app.schemas.common import Envelope, ListEnvelope, paged, single
from app.schemas.institution import InstitutionOut

router = APIRouter(prefix="/institutions", tags=["Institutions"])


@router.get("", response_model=ListEnvelope[InstitutionOut], summary="Institutions within the caller's scope")
def list_institutions(
    request: Request,
    status_filter: str | None = Query(None, alias="status", description="Filter by institution status"),
    params: PageParams = Depends(pagination_params),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Institution).where(institution_scope_clause(user))
    if status_filter:
        stmt = stmt.where(Institution.status == status_filter)
    stmt = stmt.order_by(Institution.name, Institution.id)
    items, total = paginate(db, stmt, params)
    return paged(
        [InstitutionOut.model_validate(i) for i in items],
        request_id=get_request_id(request),
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/{institution_id}", response_model=Envelope[InstitutionOut], summary="Institution profile")
def get_institution(
    institution_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    institution = get_institution_in_scope(db, user, institution_id)
    return single(InstitutionOut.model_validate(institution), get_request_id(request))
