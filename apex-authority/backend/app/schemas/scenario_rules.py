"""Deterministic business-rule validation for scenarios (proposed shared module).

Module 1's POST /scenarios/{id}/validate should reuse (or must be equivalent to) this function so
AI drafts and hand-written scenarios obey identical rules. Pure function: no I/O, no provider calls.
"""
from __future__ import annotations

from collections import Counter

from app.schemas.scenario import (
    ROLE_ID_PATTERN, Scenario, ScenarioDraftRequest, ValidationIssue, ValidationResult,
)

MAX_TEXT = 4000


def validate_scenario(scenario: Scenario, request: ScenarioDraftRequest | None = None) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    err = lambda f, i: errors.append(ValidationIssue(field=f, issue=i))
    warn = lambda f, i: warnings.append(ValidationIssue(field=f, issue=i))
    limit = scenario.duration_minutes * 60

    if not 5 <= scenario.duration_minutes <= 120:
        err("duration_minutes", "must be between 5 and 120")
    if not scenario.learning_objectives:
        err("learning_objectives", "at least one learning objective is required")
    if len(scenario.roles) < 2:
        err("roles", "at least two roles are required")
    for f, v in (("title", scenario.title), ("description", scenario.description)):
        if not v.strip():
            err(f, "must not be empty")
        if len(v) > MAX_TEXT:
            err(f, f"must be at most {MAX_TEXT} characters")

    role_ids = [r.role_id for r in scenario.roles]
    role_set = set(role_ids)
    for rid, n in Counter(role_ids).items():
        if n > 1:
            err("roles", f"duplicate role_id '{rid}'")
    for i, r in enumerate(scenario.roles):
        if not ROLE_ID_PATTERN.match(r.role_id):
            err(f"roles[{i}].role_id", "must match ^[a-z][a-z0-9_]{1,31}$")
        if not r.display_name.strip():
            err(f"roles[{i}].display_name", "must not be empty")
        if not r.briefing.strip():
            err(f"roles[{i}].briefing", "must not be empty")

    def check_roles(path: str, roles: list[str], allow_empty: bool = False):
        if not roles and not allow_empty:
            err(path, "must name at least one role")
        for rid in roles:
            if rid not in role_set:
                err(path, f"unknown role '{rid}'")

    seen_reports: set[str] = set()
    for i, rep in enumerate(scenario.initial_reports):
        if rep.report_id in seen_reports:
            err(f"initial_reports[{i}].report_id", "duplicate report_id")
        seen_reports.add(rep.report_id)
        check_roles(f"initial_reports[{i}].visible_to_roles", rep.visible_to_roles)
        if not rep.content.strip():
            err(f"initial_reports[{i}].content", "must not be empty")
    if not scenario.initial_reports:
        warn("initial_reports", "no initial reports defined")
    reported = {r for rep in scenario.initial_reports for r in rep.visible_to_roles}
    for rid in role_set - reported:
        warn("initial_reports", f"role '{rid}' receives no initial report")

    seen_events: set[str] = set()
    for i, ev in enumerate(scenario.events):
        p = f"events[{i}]"
        if ev.event_key in seen_events:
            err(f"{p}.event_key", "duplicate event_key")
        seen_events.add(ev.event_key)
        if ev.offset_seconds < 0:
            err(f"{p}.offset_seconds", "must be >= 0")
        elif ev.offset_seconds > limit:
            err(f"{p}.offset_seconds", "must not exceed scenario duration")
        cfg = ev.config
        if ev.event_type == "communication_failure":
            ft = cfg.get("failure_type")
            if ft not in {"delay", "drop", "conflicting_report", "incomplete_report"}:
                err(f"{p}.config.failure_type", "must be one of delay, drop, conflicting_report, incomplete_report")
            dur = cfg.get("duration_seconds")
            if not isinstance(dur, int) or isinstance(dur, bool) or dur < 0:
                err(f"{p}.config.duration_seconds", "must be an integer >= 0")
            elif ev.offset_seconds + dur > limit:
                warn(f"{p}.config.duration_seconds", "failure extends past scenario end")
            targets = cfg.get("target_roles")
            if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
                err(f"{p}.config.target_roles", "must be a list of role ids")
            else:
                check_roles(f"{p}.config.target_roles", targets)
        else:
            warn(f"{p}.event_type", f"event_type '{ev.event_type}' is not a known simulation event type")

    seen_dec: set[str] = set()
    if not scenario.decision_points:
        err("decision_points", "at least one decision point is required")
    for i, dp in enumerate(scenario.decision_points):
        p = f"decision_points[{i}]"
        if dp.decision_key in seen_dec:
            err(f"{p}.decision_key", "duplicate decision_key")
        seen_dec.add(dp.decision_key)
        if dp.offset_seconds < 0:
            err(f"{p}.offset_seconds", "must be >= 0")
        elif dp.offset_seconds > limit:
            err(f"{p}.offset_seconds", "must not exceed scenario duration")
        if not dp.prompt.strip():
            err(f"{p}.prompt", "must not be empty")
        check_roles(f"{p}.visible_to_roles", dp.visible_to_roles)
        opt_ids = [o.option_id for o in dp.options]
        if len(dp.options) < 2:
            err(f"{p}.options", "at least two options are required")
        if len(set(opt_ids)) != len(opt_ids):
            err(f"{p}.options", "duplicate option_id")
        if not dp.evaluation_criteria:
            err(f"{p}.evaluation_criteria", "at least one criterion is required")
        crit_ids: set[str] = set()
        for j, c in enumerate(dp.evaluation_criteria):
            cp = f"{p}.evaluation_criteria[{j}]"
            if c.criterion_id in crit_ids:
                err(f"{cp}.criterion_id", "duplicate criterion_id")
            crit_ids.add(c.criterion_id)
            if not c.weight > 0 or c.weight > 10:
                err(f"{cp}.weight", "must be > 0 and <= 10")
            for oid in c.acceptable_option_ids:
                if oid not in opt_ids:
                    err(f"{cp}.acceptable_option_ids", f"unknown option '{oid}'")
            if not c.acceptable_option_ids:
                warn(f"{cp}.acceptable_option_ids", "empty; scoring relies on scoring_notes only")
            elif set(c.acceptable_option_ids) == set(opt_ids) and len(opt_ids) > 1:
                warn(f"{cp}.acceptable_option_ids", "every option is acceptable; criterion will not discriminate")

    if request is not None:
        if scenario.domain != request.domain:
            err("domain", "does not match requested domain")
        if scenario.difficulty != request.difficulty:
            err("difficulty", "does not match requested difficulty")
        if scenario.duration_minutes != request.duration_minutes:
            err("duration_minutes", "does not match requested duration")
        if set(role_ids) != set(request.role_ids):
            err("roles", "role_ids do not match the requested role_ids")
        present = {ev.config.get("failure_type") for ev in scenario.events}
        for ft in request.communication_failures:
            if ft.value not in present:
                warn("events", f"requested failure type '{ft.value}' is not scheduled")

    if scenario.status.value != "draft":
        err("status", "AI-generated scenarios must have status 'draft'")
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
