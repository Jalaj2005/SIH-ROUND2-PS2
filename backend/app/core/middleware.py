import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.ids import new_request_id

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request id (client-supplied if well-formed) to request.state and the X-Request-ID header."""

    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _SAFE_ID.match(supplied) else new_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
