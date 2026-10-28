# Architecture (Module 0)

Monolith: one FastAPI app, one database, one API contract. Modules are routers/services inside the same package.

```
Browser (React + TS, later) --JSON REST--> FastAPI (/api/v1)
   core/        config, auth seam (deps.get_current_user), permissions, errors, pagination, enums
   models/      SQLAlchemy 2.0 models (14 tables)
   services/    business logic (audit_service now; workflow/compliance/... in later modules)
   routers/     thin HTTP layer registered in api/v1/router.py
   -> PostgreSQL (SQLite for local dev/tests)
```

Design rules fixed here for later modules:
1. **Auth seam.** All endpoints use `Depends(get_current_user)` / `require_roles(...)`. Swapping demo auth for real identity means replacing that one dependency.
2. **Scope on the server.** Institution-level scope lives in `core/permissions.py`:
   `institution_scope_clause(user)` (filter institutions), `institution_id_in_scope(user, Model.institution_id)`
   (filter any table with an institution_id), `get_institution_in_scope(db, user, id)` (404 vs 403).
   Record-level rules (assigned cases, etc.) are added by the owning module on top of this.
3. **Envelopes.** Return `single(data, request_id)` / `paged(items, ...)`; declare `Envelope[T]` / `ListEnvelope[T]` as `response_model`.
4. **Errors.** Raise `AppError` (or `forbidden()`, `not_found()`, `conflict()`); never hand-build error JSON.
5. **Audit in the same transaction.** `audit_service.log_event(...)` stages a row; the router commits once.
6. **Timestamps** are timezone-aware UTC (`UTCDateTime` rejects naive datetimes). Use `core.ids.utcnow()`.
7. **IDs** are prefixed strings from `core.ids.new_id("app")`; seed data uses fixed readable IDs.
8. **Stage references**: `workflow_transitions.from_stage/to_stage` and `application_stage_history.from_stage/to_stage`
   store `stage_code` values scoped to the template (not stage row IDs).
9. **Status changes** only through Module 1's transition endpoint; no PATCH of `applications.status/current_stage_id`.

## Module 1 notes for other modules
- `services/workflow_service.perform_transition(db, user=, application=, action=, reason=, metadata=, request_id=,
  allow_managed=False)` is the **only** writer of `applications.status/current_stage_id/assigned_to` after creation. It
  stages writes and does not commit. Other modules (e.g. Module 5) call it rather than updating the application row.
- **Module 5 (EVC):** `SCHEDULE_EVC` / `COMPLETE_EVC` are refused by the public endpoint (`MANAGED_ACTIONS`). Create/update the
  `evc_records` row and call `perform_transition(..., allow_managed=True)` in the same transaction. Completing EVC auto-routes
  to COMMITTEE_REVIEW; it never approves.
- **Module 4 (analytics):** `stage_entered_at` = latest `application_stage_history.created_at`; return counts = history rows
  with `action = RETURN_FOR_DEFICIENCY`; stage SLA = `workflow_stages.default_sla_hours`.
- **Module 3 (alerts):** transitions are audited as `entity_type="application"`, `action="APPLICATION_TRANSITION"`.
- Automatic routing = a transition with `required_role = "SYSTEM"` (max one per from-stage). Config lives in
  `seed/workflow_templates.py` and is stored in the workflow_* tables; re-running the seed upserts config rows but never
  rewinds applications or touches (append-only) history.
- Visibility: `workflow_service.application_scope_clause(user)` (lists) and `get_application_for_user(db, user, id)` (records)
  add "drafts are institution-private" on top of Module 0's institution scope. Reuse them for anything application-scoped.

