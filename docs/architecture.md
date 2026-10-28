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
