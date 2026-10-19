"""PLACEHOLDER auth for Module 2 development.

Module 1 owns real authentication/authorisation. Until it lands, development/test builds accept
`X-Demo-User-Id` (UUID) and `X-Demo-Role` (instructor|commander|trainee) headers. Outside
development/test this dependency always answers 401. Module 1 should replace `get_current_user`
(same signature / `CurrentUser` shape) and keep `require_instructor` as-is.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header

from app.core.config import Settings, load_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: str  # instructor | commander | trainee


def get_settings() -> Settings:  # overridden in tests / replaced by app wiring
    return load_settings()


def get_current_user(
    x_demo_user_id: str | None = Header(default=None),
    x_demo_role: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if not settings.demo_auth_enabled or not x_demo_user_id or not x_demo_role:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    try:
        uid = uuid.UUID(x_demo_user_id)
    except ValueError:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    if x_demo_role not in {"instructor", "commander", "trainee"}:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    return CurrentUser(id=uid, role=x_demo_role)


def require_instructor(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "instructor":
        raise AppError(403, "FORBIDDEN", "Instructor role required.")
    return user
