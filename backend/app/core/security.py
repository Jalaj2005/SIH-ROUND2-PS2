"""PROTOTYPE authentication helpers (signed bearer token for seeded demo users). Not production identity."""
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.errors import unauthenticated

ALGORITHM = "HS256"


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "typ": "prototype-demo",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise unauthenticated("Token has expired.", code="TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise unauthenticated("Invalid token.", code="INVALID_TOKEN")
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise unauthenticated("Invalid token.", code="INVALID_TOKEN")
    return subject
