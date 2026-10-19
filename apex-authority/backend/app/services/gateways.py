"""Seam between Module 2 and Module 1.

Module 1 should provide an object satisfying `SessionGateway` (calling its shared service directly, per the
spec's implementation note) and override the `get_session_gateway` dependency. Until then the fixture
gateway serves the sample logs in app/fixtures/. Module 2 never reads Module 1 tables directly.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Protocol

from app.core.security import CurrentUser
from app.schemas.aar import AARInput

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class SessionNotFound(Exception): ...
class SessionNotEnded(Exception): ...
class SessionAccessDenied(Exception): ...


class SessionGateway(Protocol):
    def get_aar_input(self, session_id: uuid.UUID, requester: CurrentUser) -> AARInput:
        """Canonical AAR input (spec 6.3). Must raise SessionNotFound / SessionNotEnded / SessionAccessDenied."""
        ...


class FixtureSessionGateway:
    """Serves JSON fixtures. `register()` lets tests add variants (e.g. an unfinished session)."""

    def __init__(self) -> None:
        self._inputs: dict[uuid.UUID, AARInput] = {}
        self._unfinished: set[uuid.UUID] = set()
        sample = json.loads((FIXTURE_DIR / "aar_input_sample.json").read_text())
        self.register(AARInput.model_validate(sample))

    def register(self, aar_input: AARInput, ended: bool = True) -> None:
        self._inputs[aar_input.session_id] = aar_input
        if not ended:
            self._unfinished.add(aar_input.session_id)

    def get_aar_input(self, session_id: uuid.UUID, requester: CurrentUser) -> AARInput:
        if requester.role != "instructor":
            raise SessionAccessDenied()
        if session_id not in self._inputs:
            raise SessionNotFound()
        if session_id in self._unfinished:
            raise SessionNotEnded()
        return self._inputs[session_id].model_copy(deep=True)
