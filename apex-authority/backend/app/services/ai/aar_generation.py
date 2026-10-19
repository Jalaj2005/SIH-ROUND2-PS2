"""Feature B: evidence-grounded After-Action Review.

The model receives a minimised evidence package and may only cite ids/metric keys from it. Official
scores/timestamps are never generated or altered here: they are copied from Module 1 data.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CurrentUser
from app.schemas.aar import (
    AARCreateRequest, AARInput, AARReport, AARStatus, AARUpdateRequest, GeneratedAAR,
)
from app.schemas.scenario import ValidationIssue
from app.services.ai.generation import generate_validated
from app.services.ai.prompts import aar_v1 as prompt
from app.services.ai.provider import LLMProvider
from app.services.ai.repository import AARRecord, InMemoryAIStore
from app.services.ai.sanitize import clean_obj, clean_text
from app.services.gateways import SessionAccessDenied, SessionGateway, SessionNotEnded, SessionNotFound

MAX_EVENTS = 200
_PII_KEY = re.compile(r"name|email|phone|address|user_id|ip_addr|token|secret|password", re.IGNORECASE)
_SAFE_REF = re.compile(r"[^A-Za-z0-9_.\-]")


def _redact(obj: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(obj, dict):
        return {k: _redact(v, depth + 1) for k, v in obj.items() if not _PII_KEY.search(str(k))}
    if isinstance(obj, list):
        return [_redact(v, depth + 1) for v in obj[:20]]
    if isinstance(obj, str):
        return clean_text(obj, 300)
    return obj


class EvidencePackage:
    def __init__(self, data: dict[str, Any], allowed_refs: list[str], limitations: list[str], warnings: list[str]):
        self.data, self.allowed_refs, self.limitations, self.warnings = data, allowed_refs, limitations, warnings


def build_evidence(aar: AARInput) -> EvidencePackage:
    """Minimise what leaves the platform: role ids only (no names/user ids), redacted payloads, bounded size."""
    limitations: list[str] = []
    warnings: list[str] = []
    if aar.session_summary.ended_at is None:
        raise AppError(409, "SESSION_NOT_ENDED", "AAR can only be generated for a completed session.")
    if not aar.events and not aar.decisions:
        raise AppError(422, "INSUFFICIENT_EVIDENCE",
                       "The session has no recorded events or decisions, so no evidence-based review can be generated.")

    referenced = {r for d in aar.decisions for r in d.available_evidence_refs}
    events = sorted(aar.events, key=lambda e: e.sequence_no)
    if len(events) > MAX_EVENTS:
        keep = {str(e.event_id) for e in events if str(e.event_id) in referenced}
        for e in events:
            if len(keep) >= MAX_EVENTS:
                break
            keep.add(str(e.event_id))
        events = [e for e in events if str(e.event_id) in keep]
        limitations.append(f"Only {len(events)} of {len(aar.events)} events were supplied to the analysis (size limit); "
                           "events cited by decisions were prioritised.")
        warnings.append("event_log_truncated")

    metrics = {k: v for k, v in aar.metrics.items() if v is not None}
    missing = sorted(k for k, v in aar.metrics.items() if v is None)
    if not metrics:
        limitations.append("No computed metrics were available for this session.")
    if missing:
        limitations.append("Metrics not available: " + ", ".join(missing) + ".")
    if not aar.decisions:
        limitations.append("No decisions were recorded, so decision quality could not be assessed.")
    if not aar.events:
        limitations.append("No events were recorded in the supplied log.")
    no_snapshot = [d for d in aar.decisions if not d.available_evidence_refs]
    if no_snapshot:
        limitations.append(f"{len(no_snapshot)} decision(s) have no recorded evidence snapshot, so what information "
                           "was available at decision time cannot be confirmed.")
    no_rationale = [d for d in aar.decisions if not (d.rationale or "").strip()]
    if no_rationale:
        limitations.append(f"{len(no_rationale)} decision(s) have no rationale recorded.")

    data = {
        "scenario": {"title": clean_text(aar.scenario.title, 200),
                     "learning_objectives": [clean_text(o, 200) for o in aar.scenario.learning_objectives]},
        "session_summary": {"started_at": aar.session_summary.started_at, "ended_at": aar.session_summary.ended_at,
                            "participant_count": aar.session_summary.participant_count},
        "roles_present": sorted({p.role_id for p in aar.participants}),
        "metrics": metrics,
        "decisions": [{
            "decision_id": str(d.decision_id), "decision_key": d.decision_key, "role_id": d.role_id,
            "selected_option_id": d.selected_option_id, "rationale": clean_text(d.rationale or "", 1000),
            "submitted_at": d.submitted_at, "available_evidence_refs": d.available_evidence_refs,
            "score": d.score, "score_breakdown": d.score_breakdown,
        } for d in aar.decisions],
        "events": [{
            "event_id": str(e.event_id), "sequence_no": e.sequence_no, "event_type": e.event_type,
            "occurred_at": e.occurred_at, "scenario_offset_seconds": e.scenario_offset_seconds,
            "payload": _redact(e.payload),
        } for e in events],
    }
    allowed = [str(e.event_id) for e in events] + [str(d.decision_id) for d in aar.decisions] + list(metrics.keys())
    return EvidencePackage(data, allowed, limitations, warnings)


def validate_report(rep: GeneratedAAR | AARUpdateRequest, allowed: set[str], objectives: list[str],
                    strict_required: bool = True) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    add = lambda f, i: issues.append(ValidationIssue(field=f, issue=i))
    norm = {o.strip().casefold() for o in objectives}

    def refs(path: str, rs: list[str], required: bool):
        if required and not rs:
            add(path, "at least one evidence reference is required")
        for r in rs:
            if r not in allowed:
                add(path, "references an id or metric key that is not in the evidence package")

    if getattr(rep, "executive_summary", None) is not None and not rep.executive_summary.strip():
        add("executive_summary", "must not be empty")
    if rep.key_observations is not None:
        if strict_required and not rep.key_observations:
            add("key_observations", "at least one observation is required")
        for i, o in enumerate(rep.key_observations):
            if not o.observation.strip():
                add(f"key_observations[{i}].observation", "must not be empty")
            refs(f"key_observations[{i}].evidence_refs", o.evidence_refs, required=o.classification.value == "fact")
    for name in ("strengths", "improvement_areas"):
        items = getattr(rep, name)
        if items is not None:
            for i, f in enumerate(items):
                if not f.text.strip():
                    add(f"{name}[{i}].text", "must not be empty")
                refs(f"{name}[{i}].evidence_refs", f.evidence_refs, required=True)
    if rep.recommendations is not None:
        for i, r in enumerate(rep.recommendations):
            if not r.text.strip():
                add(f"recommendations[{i}].text", "must not be empty")
            if r.related_learning_objective.strip().casefold() not in norm:
                add(f"recommendations[{i}].related_learning_objective", "must match one of the scenario's learning objectives")
    return issues


class AARGenerationService:
    def __init__(self, provider: LLMProvider, store: InMemoryAIStore, gateway: SessionGateway, settings: Settings, sleep=None):
        self.provider, self.store, self.gateway, self.settings = provider, store, gateway, settings
        self._sleep = sleep or time.sleep

    def create(self, req: AARCreateRequest, user: CurrentUser) -> AARRecord:
        try:
            aar_input = self.gateway.get_aar_input(req.session_id, user)
        except SessionNotFound:
            raise AppError(404, "NOT_FOUND", "Session not found.")
        except SessionNotEnded:
            raise AppError(409, "SESSION_NOT_ENDED", "AAR can only be generated for a completed session.")
        except SessionAccessDenied:
            raise AppError(403, "FORBIDDEN", "You are not authorised to review this session.")

        pkg = build_evidence(aar_input)  # may raise 409/422 BEFORE any provider call
        allowed = set(pkg.allowed_refs)
        objectives = aar_input.scenario.learning_objectives

        def build(errors):
            return prompt.build_user_prompt(pkg.data, language=req.language,
                                            include_individual_feedback=req.include_individual_feedback,
                                            allowed_refs=pkg.allowed_refs, validation_errors=errors)

        gen, _attempts = generate_validated(
            provider=self.provider, settings=self.settings, system=prompt.SYSTEM, build_prompt=build,
            response_model=GeneratedAAR, validate=lambda g: validate_report(g, allowed, objectives), sleep=self._sleep,
        )
        limitations = list(dict.fromkeys(pkg.limitations + [clean_text(l, 500) for l in gen.evidence_limitations if l.strip()]))
        now = datetime.now(timezone.utc)
        report = AARReport(
            id=uuid.uuid4(), session_id=aar_input.session_id, status=AARStatus.draft, title=gen.title,
            executive_summary=gen.executive_summary, key_observations=gen.key_observations, strengths=gen.strengths,
            improvement_areas=gen.improvement_areas, recommendations=gen.recommendations, evidence_limitations=limitations,
            follow_up_scenario_brief=gen.follow_up_scenario_brief, model_provider=self.provider.name,
            model_name=self.provider.model_name, prompt_version=prompt.PROMPT_VERSION, created_at=now,
        )
        rec = AARRecord(
            report=report, created_by=user.id, allowed_refs=pkg.allowed_refs,
            metrics_snapshot=dict(aar_input.metrics), scenario_title=aar_input.scenario.title,
            objectives=list(objectives),
            session_window=(aar_input.session_summary.started_at, aar_input.session_summary.ended_at),
            warnings=pkg.warnings,
            versions=[{"version": 1, "source": "ai", "at": now, "by": None, "report": report.model_dump(mode="json")}],
        )
        self.store.save_aar(rec)
        return rec

    # ---- instructor workflow -------------------------------------------------
    def _owned(self, aar_id: uuid.UUID, user: CurrentUser) -> AARRecord:
        rec = self.store.get_aar(aar_id)
        if rec is None or rec.created_by != user.id:
            raise AppError(404, "NOT_FOUND", "Report not found.")
        return rec

    def get(self, aar_id: uuid.UUID, user: CurrentUser) -> AARRecord:
        return self._owned(aar_id, user)

    def edit(self, aar_id: uuid.UUID, patch: AARUpdateRequest, user: CurrentUser) -> AARRecord:
        rec = self._owned(aar_id, user)
        fields = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
        if not fields:
            raise AppError(422, "VALIDATION_ERROR", "No editable fields supplied.", [{"field": "$", "issue": "empty patch"}])
        issues = validate_report(patch, set(rec.allowed_refs), rec.objectives, strict_required=False)
        if issues:
            raise AppError(422, "VALIDATION_ERROR", "Edited report failed validation.", [i.model_dump() for i in issues])
        now = datetime.now(timezone.utc)
        updates = {k: getattr(patch, k) for k in fields}  # keep parsed sub-models
        # Any edit invalidates a prior review: back to draft, reviewer cleared, new version appended.
        rec.report = rec.report.model_copy(update={**updates, "status": AARStatus.draft, "reviewed_at": None, "reviewed_by": None})
        rec.versions.append({"version": len(rec.versions) + 1, "source": "instructor", "at": now, "by": str(user.id),
                             "report": rec.report.model_dump(mode="json")})
        return rec

    def review(self, aar_id: uuid.UUID, user: CurrentUser) -> AARRecord:
        rec = self._owned(aar_id, user)
        rec.report = rec.report.model_copy(update={"status": AARStatus.reviewed, "reviewed_at": datetime.now(timezone.utc),
                                                    "reviewed_by": user.id})
        return rec

    def mark_exported(self, rec: AARRecord) -> None:
        rec.report = rec.report.model_copy(update={"status": AARStatus.exported})
