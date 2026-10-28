from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.core.errors import AppError, unauthenticated
from app.core.permissions import describe_scope
from app.core.security import create_access_token
from app.models.identity import User
from app.schemas.auth import DemoLoginRequest, LoginOut, MeOut, ScopeOut, UserOut
from app.schemas.common import Envelope, single
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["Auth (prototype)"])


@router.post(
    "/demo-login",
    response_model=Envelope[LoginOut],
    summary="PROTOTYPE login as a seeded demo user (no password)",
)
def demo_login(
    payload: DemoLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    request_id = get_request_id(request)
    if not settings.demo_auth_enabled:
        raise AppError("DEMO_AUTH_DISABLED", "Demo login is disabled in this environment.", 403)

    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active:
        audit_service.log_event(
            db,
            action="AUTH_DEMO_LOGIN_FAILED",
            entity_type="auth",
            entity_id="demo-login",
            after={"email": email[:200]},
            request_id=request_id,
        )
        db.commit()
        raise unauthenticated("Unknown or inactive demo user.")

    audit_service.log_event(
        db,
        action="AUTH_DEMO_LOGIN",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        request_id=request_id,
    )
    db.commit()
    data = LoginOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
        scope=ScopeOut(**describe_scope(user)),
    )
    return single(data, request_id)


@router.get("/me", response_model=Envelope[MeOut], summary="Current user, role and allowed scope")
def me(request: Request, user: User = Depends(get_current_user)):
    data = MeOut(user=UserOut.model_validate(user), scope=ScopeOut(**describe_scope(user)))
    return single(data, get_request_id(request))
