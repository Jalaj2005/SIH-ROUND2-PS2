import uuid

from fastapi import APIRouter, Depends, Response

from app.api.v1.deps import get_aar_service
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CurrentUser, get_settings, require_instructor
from app.schemas.aar import AARCreateRequest, AARCreateResponse, AARReport, AARStatus, AARUpdateRequest
from app.services.ai.aar_generation import AARGenerationService
from app.services.ai.aar_pdf import render_aar_pdf
from app.services.ai.repository import AARRecord

router = APIRouter(prefix="/ai/aar", tags=["ai-aar"])


def _out(rec: AARRecord) -> AARCreateResponse:
    return AARCreateResponse(aar_id=rec.report.id, session_id=rec.report.session_id, status=rec.report.status,
                             report=rec.report, warnings=rec.warnings, version_count=len(rec.versions))


@router.post("", status_code=201, response_model=AARCreateResponse)
def create_aar(body: AARCreateRequest, user: CurrentUser = Depends(require_instructor),
               svc: AARGenerationService = Depends(get_aar_service)):
    return _out(svc.create(body, user))


@router.get("/{aar_id}", response_model=AARCreateResponse)
def get_aar(aar_id: uuid.UUID, user: CurrentUser = Depends(require_instructor),
            svc: AARGenerationService = Depends(get_aar_service)):
    return _out(svc.get(aar_id, user))


@router.patch("/{aar_id}", response_model=AARCreateResponse)
def edit_aar(aar_id: uuid.UUID, body: AARUpdateRequest, user: CurrentUser = Depends(require_instructor),
             svc: AARGenerationService = Depends(get_aar_service)):
    return _out(svc.edit(aar_id, body, user))


@router.post("/{aar_id}/review", response_model=AARCreateResponse)
def review_aar(aar_id: uuid.UUID, user: CurrentUser = Depends(require_instructor),
               svc: AARGenerationService = Depends(get_aar_service)):
    return _out(svc.review(aar_id, user))


@router.get("/{aar_id}/pdf")
def aar_pdf(aar_id: uuid.UUID, user: CurrentUser = Depends(require_instructor),
            svc: AARGenerationService = Depends(get_aar_service), settings: Settings = Depends(get_settings)):
    rec = svc.get(aar_id, user)
    if settings.aar_require_review_for_export and rec.report.status == AARStatus.draft:
        raise AppError(409, "AAR_NOT_REVIEWED", "Review the report before exporting it to PDF.")
    pdf = render_aar_pdf(rec)  # rendered from stored data only
    svc.mark_exported(rec)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="aar-{rec.report.id}.pdf"'})
