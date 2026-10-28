from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  (register all tables on Base.metadata)
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestIDMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Prototype backend for the AICTE PS 4 workflow, compliance and alert system. "
            "Synthetic data only; no live AICTE integration; no statutory decisioning."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(RequestIDMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
