from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_request_id
from app.schemas.common import Envelope
from pydantic import BaseModel

router = APIRouter(tags=["Foundation"])


class HealthOut(BaseModel):
    status: str
    service: str
    version: str
    database: str


@router.get("/health", response_model=Envelope[HealthOut], summary="Service health check")
def health(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    data = HealthOut(
        status="ok" if database == "ok" else "degraded",
        service=settings.app_name,
        version=settings.version,
        database=database,
    )
    return {"data": data, "meta": {"request_id": get_request_id(request)}}
