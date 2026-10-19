"""Module 2 entry point. NOTE: Module 1 owns the real app factory; merge by including the routers below
and the `install_error_handling` call. /health is a placeholder until Module 1's lands."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import ai_aar, ai_scenarios, ai_status
from app.core.config import load_settings
from app.core.errors import install_error_handling


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Apex Authority API", version="0.1.0")
    install_error_handling(app)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])
    for r in (ai_scenarios.router, ai_aar.router, ai_status.router):
        app.include_router(r, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
