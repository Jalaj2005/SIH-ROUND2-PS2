"""Standard error envelope (spec 8.4) and exception handlers."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_body(code: str, message: str, details: list[dict[str, Any]] | None, request: Request) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
        }
    }


_HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "INVALID_STATE", 429: "RATE_LIMITED"}


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details, request), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [
            # never echo submitted values back (they may be untrusted/sensitive); only location + message
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "issue": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(error_body("VALIDATION_ERROR", "Request failed validation.", details, request), status_code=422)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        code = _HTTP_CODES.get(exc.status_code, "ERROR")
        return JSONResponse(error_body(code, str(exc.detail), None, request), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never expose exception text, stack traces, prompts or provider details to clients.
        return JSONResponse(error_body("INTERNAL_ERROR", "Unexpected server error.", None, request), status_code=500)
