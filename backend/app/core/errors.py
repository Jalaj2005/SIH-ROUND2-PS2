import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")


class AppError(Exception):
    """Raise anywhere; rendered in the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.headers = headers


class AppendOnlyViolation(RuntimeError):
    """Raised when code tries to update/delete an append-only row (audit log, stage history)."""


def unauthenticated(message: str = "Authentication required.", code: str = "UNAUTHENTICATED") -> AppError:
    return AppError(code, message, 401, headers={"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "You do not have permission to perform this action.") -> AppError:
    return AppError("FORBIDDEN", message, 403)


def not_found(message: str = "Resource not found.") -> AppError:
    return AppError("NOT_FOUND", message, 404)


def conflict(message: str, code: str = "CONFLICT") -> AppError:
    return AppError(code, message, 409)


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def error_body(request: Request, code: str, message: str, details: list | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            details.append(
                {"field": ".".join(loc) or None, "issue": re.sub(r"\s+", " ", str(err.get("msg", "invalid")))}
            )
        return JSONResponse(
            status_code=422,
            content=error_body(request, "VALIDATION_ERROR", "Request validation failed.", details),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("Unhandled error (request_id=%s)", getattr(request.state, "request_id", None))
        return JSONResponse(
            status_code=500,
            content=error_body(request, "INTERNAL_ERROR", "An unexpected error occurred."),
        )
