"""Central registration point: every module adds its router here. Prefix is /api/v1 for all endpoints."""
from fastapi import APIRouter

from app.routers import auth, health, institutions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(institutions.router)
# Later modules register here, e.g. api_router.include_router(applications.router)
