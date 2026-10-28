"""Workflow template configuration (stages + allowed transition map), stored in the DB tables
workflow_templates / workflow_stages / workflow_transitions by `seed_workflow_templates`.

Prototype examples only: these routes and labels are NOT claimed to be the official AICTE process.
Two categories deliberately follow different routes:
  NEW_INSTITUTION        scrutiny -> EVC -> committee -> authority decision
  EXTENSION_OF_APPROVAL  scrutiny -> authority decision (no EVC, no committee)

Conventions (see docs/architecture.md):
  * stage_code == applications.status (so every stage_code must be an ApplicationStatus value)
  * required_role == "SYSTEM" marks an automatic routing step; at most one per from-stage
  * workflow_stages.allowed_roles = roles responsible for work at that stage (the "queue"), used for display
    and assignment; the authority to perform an action is transition.required_role
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus as S
from app.core.enums import Role, SYSTEM_ROLE, WorkflowAction as A
from app.models.workflow import WorkflowStage, WorkflowTemplate, WorkflowTransition

INST, SCR, EVC, COM, REG = (
    Role.INSTITUTION_USER.value,
    Role.SCRUTINY_OFFICER.value,
    Role.EVC_COORDINATOR.value,
    Role.COMMITTEE_AUTHORITY.value,
    Role.REGIONAL_OFFICER.value,
)


@dataclass(frozen=True)
class StageDef:
    code: str
    name: str
    roles: tuple[str, ...]
    sla_hours: int | None = None  # demo values


@dataclass(frozen=True)
class TransitionDef:
    from_stage: str
    action: str
    to_stage: str
    role: str
    requires_reason: bool = False


@dataclass(frozen=True)
class TemplateDef:
    key: str
    name: str
    category: str
    stages: tuple[StageDef, ...]
    transitions: tuple[TransitionDef, ...]
    version: int = 1

    @property
    def id(self) -> str:
        return f"wft_{self.key}_v{self.version}"


def _stage(code, name, roles, sla=None) -> StageDef:
    return StageDef(str(code), name, tuple(str(r) for r in roles), sla)


def _t(frm, action, to, role, reason=False) -> TransitionDef:
    return TransitionDef(str(frm), str(action), str(to), str(role), reason)


_COMMON_HEAD = (
    _stage(S.DRAFT, "Draft", [INST]),
    _stage(S.SUBMITTED, "Submitted (routing)", [SYSTEM_ROLE]),
    _stage(S.IN_SCRUTINY, "Scrutiny", [SCR], 120),
    _stage(S.RETURNED_FOR_DEFICIENCY, "Returned for deficiency", [INST], 240),
    _stage(S.RESUBMITTED, "Resubmitted (routing)", [SYSTEM_ROLE]),
    _stage(S.RE_SCRUTINY, "Re-scrutiny", [SCR], 72),
)
_COMMON_TAIL = (
    _stage(S.APPROVED, "Approved", [REG]),
    _stage(S.REJECTED, "Rejected", [REG]),
    _stage(S.CLOSED, "Closed", []),
    _stage(S.WITHDRAWN, "Withdrawn", []),
)

_COMMON_TRANSITIONS = (
    _t(S.DRAFT, A.SUBMIT, S.SUBMITTED, INST),
    _t(S.DRAFT, A.WITHDRAW, S.WITHDRAWN, INST, True),
    _t(S.SUBMITTED, A.ROUTE_TO_SCRUTINY, S.IN_SCRUTINY, SYSTEM_ROLE),
    _t(S.IN_SCRUTINY, A.RETURN_FOR_DEFICIENCY, S.RETURNED_FOR_DEFICIENCY, SCR, True),
    _t(S.IN_SCRUTINY, A.WITHDRAW, S.WITHDRAWN, INST, True),
    _t(S.RETURNED_FOR_DEFICIENCY, A.RESUBMIT, S.RESUBMITTED, INST, True),
    _t(S.RETURNED_FOR_DEFICIENCY, A.WITHDRAW, S.WITHDRAWN, INST, True),
    _t(S.RESUBMITTED, A.ROUTE_TO_RE_SCRUTINY, S.RE_SCRUTINY, SYSTEM_ROLE),
    _t(S.RE_SCRUTINY, A.RETURN_FOR_DEFICIENCY, S.RETURNED_FOR_DEFICIENCY, SCR, True),
    _t(S.RE_SCRUTINY, A.WITHDRAW, S.WITHDRAWN, INST, True),
    _t(S.AWAITING_AUTHORITY_DECISION, A.RECORD_APPROVAL, S.APPROVED, COM, True),
    _t(S.AWAITING_AUTHORITY_DECISION, A.RECORD_REJECTION, S.REJECTED, COM, True),
    _t(S.APPROVED, A.CLOSE, S.CLOSED, REG),
    _t(S.REJECTED, A.CLOSE, S.CLOSED, REG),
)

NEW_INSTITUTION = TemplateDef(
    key="new_institution",
    name="New institution approval (with EVC and committee)",
    category="NEW_INSTITUTION",
    stages=_COMMON_HEAD
    + (
        _stage(S.EVC_PENDING, "EVC queue", [EVC], 168),
        _stage(S.EVC_SCHEDULED, "EVC scheduled", [EVC], 336),
        _stage(S.EVC_COMPLETED, "EVC completed (routing)", [SYSTEM_ROLE]),
        _stage(S.COMMITTEE_REVIEW, "Committee review", [COM], 168),
        _stage(S.AWAITING_AUTHORITY_DECISION, "Awaiting authority decision", [COM], 120),
    )
    + _COMMON_TAIL,
    transitions=_COMMON_TRANSITIONS
    + (
        _t(S.IN_SCRUTINY, A.COMPLETE_SCRUTINY, S.EVC_PENDING, SCR),
        _t(S.RE_SCRUTINY, A.COMPLETE_SCRUTINY, S.EVC_PENDING, SCR),
        _t(S.EVC_PENDING, A.SCHEDULE_EVC, S.EVC_SCHEDULED, EVC),
        _t(S.EVC_SCHEDULED, A.COMPLETE_EVC, S.EVC_COMPLETED, EVC),
        _t(S.EVC_COMPLETED, A.ROUTE_TO_COMMITTEE, S.COMMITTEE_REVIEW, SYSTEM_ROLE),
        _t(S.COMMITTEE_REVIEW, A.FORWARD_TO_AUTHORITY, S.AWAITING_AUTHORITY_DECISION, COM),
    ),
)

EXTENSION_OF_APPROVAL = TemplateDef(
    key="extension_of_approval",
    name="Extension of approval (no EVC, no committee)",
    category="EXTENSION_OF_APPROVAL",
    stages=_COMMON_HEAD
    + (_stage(S.AWAITING_AUTHORITY_DECISION, "Awaiting authority decision", [COM], 120),)
    + _COMMON_TAIL,
    transitions=_COMMON_TRANSITIONS
    + (
        _t(S.IN_SCRUTINY, A.COMPLETE_SCRUTINY, S.AWAITING_AUTHORITY_DECISION, SCR),
        _t(S.RE_SCRUTINY, A.COMPLETE_SCRUTINY, S.AWAITING_AUTHORITY_DECISION, SCR),
    ),
)

TEMPLATES: tuple[TemplateDef, ...] = (NEW_INSTITUTION, EXTENSION_OF_APPROVAL)


def validate_template(t: TemplateDef) -> None:
    """Fail fast on a broken map (used by seeding and tests)."""
    statuses = {s.value for s in S}
    roles = {r.value for r in Role} | {SYSTEM_ROLE}
    codes = [s.code for s in t.stages]
    assert len(codes) == len(set(codes)), f"{t.key}: duplicate stage codes"
    assert set(codes) <= statuses, f"{t.key}: stage code is not an ApplicationStatus: {set(codes) - statuses}"
    assert S.DRAFT.value in codes, f"{t.key}: missing DRAFT stage"
    system_from: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for tr in t.transitions:
        assert tr.from_stage in codes and tr.to_stage in codes, f"{t.key}: unknown stage in {tr}"
        assert tr.role in roles, f"{t.key}: unknown role in {tr}"
        assert (tr.from_stage, tr.action) not in seen, f"{t.key}: duplicate (from, action) {tr}"
        seen.add((tr.from_stage, tr.action))
        if tr.role == SYSTEM_ROLE:
            assert tr.from_stage not in system_from, f"{t.key}: >1 automatic step from {tr.from_stage}"
            system_from.add(tr.from_stage)
            assert not tr.requires_reason


def seed_workflow_templates(db: Session) -> int:
    """Upsert configuration rows by deterministic id (config tables are not append-only)."""
    for t in TEMPLATES:
        validate_template(t)
        db.merge(WorkflowTemplate(id=t.id, name=t.name, category=t.category, is_active=True, version=t.version))
    db.flush()
    for t in TEMPLATES:
        for i, s in enumerate(t.stages, start=1):
            db.merge(
                WorkflowStage(
                    id=f"stg_{t.key}_{s.code.lower()}", template_id=t.id, stage_code=s.code,
                    display_name=s.name, sequence=i, allowed_roles=list(s.roles), default_sla_hours=s.sla_hours,
                )
            )
        for tr in t.transitions:
            db.merge(
                WorkflowTransition(
                    id=f"wtr_{t.key}_{tr.from_stage}_{tr.action}".lower(), template_id=t.id,
                    from_stage=tr.from_stage, action=tr.action, to_stage=tr.to_stage,
                    required_role=tr.role, requires_reason=tr.requires_reason,
                )
            )
    db.flush()
    return len(TEMPLATES)
