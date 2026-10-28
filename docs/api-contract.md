# API Contract (frozen at Module 0; Module 1 section added below)

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
| 400 | invalid action | `BAD_REQUEST`, `INVALID_ACTION` |
| 401 | unauthenticated | `UNAUTHENTICATED`, `INVALID_TOKEN`, `TOKEN_EXPIRED` |
| 403 | forbidden / out of scope | `FORBIDDEN`, `DEMO_AUTH_DISABLED` |
| 404 | not found | `NOT_FOUND` |
| 409 | invalid state / conflict | `INVALID_TRANSITION`, `ACTION_MANAGED_ELSEWHERE`, `CONCURRENT_MODIFICATION`, `APPLICATION_NOT_EDITABLE`, `CONFLICT` |
| 422 | validation | `VALIDATION_ERROR` |
| 500 | unexpected | `INTERNAL_ERROR`, `WORKFLOW_CONFIG_ERROR` (no internal detail leaked) |

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

## Module 1 — Applications and workflow engine

Enum additions (additive; nothing renamed): `WorkflowAction` (action codes) and the constant `SYSTEM_ROLE = "SYSTEM"`
in `core/enums.py`. Template stage codes equal `ApplicationStatus` values; `applications.status` == current stage_code.

### Visibility rules (on top of institution/region scope above)
- **Drafts are private to the submitting institution.** Officers, management and admin get 403 for a DRAFT and it is
  excluded from their lists.
- **Acting** on a case needs the transition's `required_role` *and*, for `SCRUTINY_OFFICER`, that the case is assigned to
  them or unassigned (queue). Admin and management have no transition rights (no statutory decisions).

### `GET /applications`
Query: `status`, `institution_id`, `stage` (stage_code), `assigned_to` (user id or `me`), `category`, `q` (application
number / institution name), `page`, `page_size`. Newest-updated first. Not supported here: `due_before`, `overdue_only`
(owned by Module 4). Item:
```json
{ "id": "app_001", "application_number": "APP-2026-0001", "institution_id": "inst_001",
  "institution_name": "Demo Institute of Technology A", "category": "NEW_INSTITUTION",
  "workflow_template_id": "wft_new_institution_v1", "workflow_template_name": "New institution approval (with EVC and committee)",
  "status": "IN_SCRUTINY",
  "current_stage": { "id": "stg_new_institution_in_scrutiny", "stage_code": "IN_SCRUTINY", "display_name": "Scrutiny",
                     "sequence": 3, "default_sla_hours": 120 },
  "responsible_roles": ["SCRUTINY_OFFICER"], "assigned_to": "usr_scrutiny", "assigned_to_name": "Scrutiny Officer",
  "submitted_at": "…Z", "created_at": "…Z", "updated_at": "…Z",
  "stage_entered_at": "…Z", "stage_due_at": "…Z" }
```
`stage_due_at = stage_entered_at + default_sla_hours` (demo SLA, configurable data). `assigned_to: null` + `responsible_roles` = queue.

### `POST /applications` → 201 (INSTITUTION_USER only)
`{ "category": "NEW_INSTITUTION", "submit": false, "institution_id": "inst_001" }` (`institution_id` optional, must be the
caller's own). `submit: true` creates and submits in one call (engine auto-routes to scrutiny). Unknown category → 422.
Any of `status`, `current_stage_id`, `assigned_to`, … → 422. Returns the detail object.

### `GET /applications/{application_id}`
List item + `open_deficiency` (only while `RETURNED_FOR_DEFICIENCY`):
`{ "history_id", "reason", "returned_at", "returned_by": {id,name,role}, "checklist_code" }`.

### `PATCH /applications/{application_id}` (INSTITUTION_USER, owner only)
Editable: `category`, **only while DRAFT** (re-selects the template; the server derives the stage). Anything else —
notably `status`, `current_stage_id`, `workflow_template_id`, `assigned_to` — is **422** and nothing changes. Non-DRAFT → 409
`APPLICATION_NOT_EDITABLE`. Audited as `APPLICATION_UPDATED`.

### `GET /applications/{application_id}/allowed-actions`
```json
{ "data": { "application_id": "app_001", "status": "IN_SCRUTINY",
            "actions": [ { "action": "COMPLETE_SCRUTINY", "label": "Mark scrutiny complete", "to_stage": "EVC_PENDING",
                           "to_stage_display_name": "EVC queue", "requires_reason": false } ] }, "meta": { "request_id": "req_abc" } }
```
Computed by the same rules as the transition endpoint (role, scope, assignment). EVC steps and automatic steps are never listed.

### `POST /applications/{application_id}/transitions` → 200 (the only way status/stage change)
```json
{ "action": "RETURN_FOR_DEFICIENCY", "reason": "Lease document is missing an authorised signature.",
  "metadata": { "checklist_code": "LEASE_SIGNATURE" } }
```
Body accepts only `action`, `reason`, `metadata` (extra fields such as `status`/`to_stage` → 422). `metadata` ≤ 4000 chars;
`document_ids` (≤ 20) must be documents of the same institution; server keys (`transition_id`, `auto`, `responds_to`,
`assigned_to_before/after`, `triggered_by_action`) cannot be forged. Returns the detail object. Check order:

| Order | Condition | Result |
|---|---|---|
| 1 | no/invalid token | 401 |
| 2 | case missing / out of scope / someone else's draft | 404 / 403 |
| 3 | action not defined in this case's template | 400 `INVALID_ACTION` |
| 4 | action exists but not from the current stage | 409 `INVALID_TRANSITION` |
| 5 | wrong role, or an automatic (`SYSTEM`) step | 403 |
| 6 | EVC step (`SCHEDULE_EVC`, `COMPLETE_EVC`) via this endpoint | 409 `ACTION_MANAGED_ELSEWHERE` (Module 5) |
| 7 | scrutiny case assigned to another officer | 403 |
| 8 | `reason` missing/blank where required | 422 `{"field":"reason","issue":"required"}` |
| 9 | bad `document_ids` | 422 `metadata.document_ids` |
| 10 | case changed concurrently | 409 `CONCURRENT_MODIFICATION` |

On success one transaction writes: the status/stage/assignment change, an `application_stage_history` row (actor,
timestamp, reason, metadata) and an `audit_logs` row (`APPLICATION_TRANSITION`, before/after, request_id). After the user's
step the engine follows any automatic routing step (`required_role = SYSTEM`), each also recorded and audited
(`metadata.auto = true`, `metadata.triggered_by_action`).

### `GET /applications/{application_id}/history`
Chronological (paged). `entry_type` is `STAGE_TRANSITION` or `AUDIT_EVENT` (audit events for the application that are not
already stage rows, e.g. `APPLICATION_UPDATED`):
`{ id, entry_type, action, from_stage, to_stage, reason, actor:{id,name,role}, created_at, metadata }`.

### `GET /workflow-templates`
Any authenticated user. Each template: `{ id, name, category, version, is_active, stages:[{stage_code, display_name,
sequence, allowed_roles, default_sla_hours}], transitions:[{from_stage, action, to_stage, required_role, requires_reason}] }`.
`required_role: "SYSTEM"` = automatic routing step.

### Seeded demo routes (configuration data, not official AICTE routes)
- `NEW_INSTITUTION`: DRAFT → SUBMITTED →(auto) IN_SCRUTINY ⇄ RETURNED_FOR_DEFICIENCY → RESUBMITTED →(auto) RE_SCRUTINY →
  EVC_PENDING → EVC_SCHEDULED → EVC_COMPLETED →(auto) COMMITTEE_REVIEW → AWAITING_AUTHORITY_DECISION → APPROVED/REJECTED → CLOSED
- `EXTENSION_OF_APPROVAL`: same until scrutiny, then COMPLETE_SCRUTINY → AWAITING_AUTHORITY_DECISION (no EVC, no committee)
- `WITHDRAW` (reason required) from DRAFT, IN_SCRUTINY, RE_SCRUTINY, RETURNED_FOR_DEFICIENCY (institution user).
- `RECORD_APPROVAL` / `RECORD_REJECTION` need `COMMITTEE_AUTHORITY` and a reason: a human-recorded outcome only.

## Not yet implemented (owned by later modules)
`/dashboard/summary`, compliance, documents, EVC, alerts, analytics, `/audit-logs`, `/admin/run-deadline-scan`.

