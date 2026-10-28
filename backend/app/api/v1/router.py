"""Central registration point: every module adds its router here. Prefix is /api/v1 for all endpoints."""
from fastapi import APIRouter

from app.routers import applications, auth, health, institutions, workflow

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(institutions.router)
api_router.include_router(applications.router)   # Module 1
api_router.include_router(workflow.router)       # Module 1
# Later modules register here
