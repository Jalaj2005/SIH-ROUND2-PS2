# API Contract (frozen at Module 0)

Base path `/api/v1`. JSON. Bearer auth. Interactive docs: `/docs`, schema: `/openapi.json`.
Changing a shared endpoint, field or enum requires an integrator decision and an update to this file.

## Envelopes

Single resource
```json
{ "data": { "id": "inst_001" }, "meta": { "request_id": "req_abc" } }
```
List
```json
{ "data": [], "meta": { "request_id": "req_abc", "page": 1, "page_size": 20, "total": 0 } }
```
Error
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Request validation failed.",
             "details": [{ "field": "email", "issue": "Field required" }], "request_id": "req_abc" } }
```
Every response carries `X-Request-ID`. A client may send its own `X-Request-ID` (`[A-Za-z0-9_.-]{1,64}`).

| HTTP | Meaning | Error codes used so far |
|---|---|---|
| 200/201/204 | success | — |
| 400 | invalid action | `BAD_REQUEST` |
| 401 | unauthenticated | `UNAUTHENTICATED`, `INVALID_TOKEN`, `TOKEN_EXPIRED` |
| 403 | forbidden / out of scope | `FORBIDDEN`, `DEMO_AUTH_DISABLED` |
| 404 | not found | `NOT_FOUND` |
| 409 | invalid state / conflict | `CONFLICT` (Module 1+) |
| 422 | validation | `VALIDATION_ERROR` |
| 500 | unexpected | `INTERNAL_ERROR` (no internal detail leaked) |

## Conventions
- **Pagination:** `page` (default 1, ≥1), `page_size` (default 20, 1–100). Out-of-range → 422. Pages beyond the end return `data: []`.
- **Filtering:** documented query params per endpoint (`status`, `institution_id`, `stage`, `assigned_to`, `due_before`, `overdue_only`).
- **Dates:** ISO 8601, stored UTC.
- **IDs:** prefixed strings (`inst_`, `usr_`, `app_`, `comp_`, `doc_`, `evc_`, `ntf_`, `esc_`, `aud_`, …).
- **Auth:** `Authorization: Bearer <token>` from `POST /auth/demo-login`. Prototype authentication only.
- **Authorization:** role + record scope enforced server-side on every protected endpoint.
- **Idempotent alerts:** `notifications.dedupe_key` is unique among `ACTIVE` notifications (DB-enforced partial unique index).

## Scope rules (institution level)
| Role | Institutions visible |
|---|---|
| INSTITUTION_USER | only `users.institution_id` |
| SCRUTINY_OFFICER, REGIONAL_OFFICER, EVC_COORDINATOR, COMPLIANCE_OFFICER, COMMITTEE_AUTHORITY | institutions with `region_id == users.region_id`; none if the user has no region |
| SENIOR_MANAGEMENT, SYSTEM_ADMIN | all |
| unknown role / missing scope data | none (fail closed) |

Out-of-scope record → **403 `FORBIDDEN`**; missing record → **404 `NOT_FOUND`**.

## Foundation endpoints

### `GET /health` (no auth)
```json
{ "data": { "status": "ok", "service": "AICTE PS4 Prototype API", "version": "0.1.0", "database": "ok" },
  "meta": { "request_id": "req_abc" } }
```

### `POST /auth/demo-login` (no auth; prototype)
Request: `{ "email": "scrutiny.officer@example.test" }` (case-insensitive; seeded active users only)
```json
{ "data": { "access_token": "<jwt>", "token_type": "bearer", "expires_in": 28800,
            "user": { "id": "usr_scrutiny", "name": "Scrutiny Officer", "email": "scrutiny.officer@example.test",
                      "role": "SCRUTINY_OFFICER", "institution_id": null, "region_id": "reg_central", "is_active": true },
            "scope": { "scope_type": "REGION", "institution_id": null, "region_id": "reg_central" },
            "prototype_auth": true, "notice": "Prototype authentication ..." },
  "meta": { "request_id": "req_abc" } }
```
401 for unknown/inactive user; 403 `DEMO_AUTH_DISABLED` when `DEMO_AUTH_ENABLED=false`. Success and failure are audited.

### `GET /auth/me`
Returns `{ user, scope }` as above.

### `GET /institutions`
Query: `status`, `page`, `page_size`. Returns only institutions in the caller's scope, ordered by name.

### `GET /institutions/{institution_id}`
Item: `{ id, name, institution_code, region_id, status }`.

## Shared enums
`Role`, `ScopeType`, `ApplicationStatus` (15 prototype states), `AlertSeverity` (INFO/WARNING/HIGH/CRITICAL),
`PriorityBand` (LOW/MEDIUM/HIGH/CRITICAL), `ComplianceItemType` (UNDERTAKING/EVIDENCE_SUBMISSION/DOCUMENT_VALIDITY),
`ComplianceStatus`, `DeadlineState` (derived), `VerificationStatus`, `EvcStatus`, `NotificationStatus`, `EscalationStatus`
— defined in `backend/app/core/enums.py`. Values beyond the brief's examples (compliance/EVC/notification statuses)
are Module 0 proposals; confirm or change them before Modules 1–5 depend on them.

## Data model
14 tables, exactly the entities in brief §8: `users, institutions, applications, workflow_templates, workflow_stages,
workflow_transitions, application_stage_history, compliance_items, documents, evc_records, notifications, escalations,
audit_logs, workflow_rules` (the brief's "workflow_rules / deadline_policies" is one table). Small additions beyond the
brief's minimum fields: `created_at` on several tables, `updated_at` on applications/compliance_items.

## Not in Module 0 (owned by later modules)
`/dashboard/summary`, applications, workflow, compliance, documents, EVC, alerts, analytics, `/audit-logs`,
`/admin/run-deadline-scan`.
