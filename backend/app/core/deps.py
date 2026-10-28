from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import Role
from app.core.errors import forbidden, unauthenticated
from app.core.ids import new_request_id
from app.core.permissions import parse_role
from app.core.security import decode_access_token
from app.models.identity import User

_bearer = HTTPBearer(auto_error=False, description="Prototype demo token from POST /api/v1/auth/demo-login")


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Single auth seam: replace this dependency to swap prototype auth for real identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated()
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None or not user.is_active:
        raise unauthenticated("User not found or inactive.")
    return user


def require_roles(*roles: Role):
    allowed = frozenset(roles)

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if parse_role(user) not in allowed:
            raise forbidden("Your role is not permitted to perform this action.")
        return user

    return _dependency
