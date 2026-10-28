# AICTE PS 4 — Integrated Approval Workflow, Compliance & Alert Prototype

Prototype built from the *AICTE PS 4 Claude-Ready Prototype Build Brief* (v1.0).
**Synthetic data only. No live AICTE integration. The system never makes statutory approval decisions.**

## Status

| Module | State |
|---|---|
| 0 — Shared foundation, DB, API contract | **Implemented (this commit)** |
| 1–7 | Not started |

Module 0 delivers: FastAPI app under `/api/v1`, SQLAlchemy models for every shared table, standard
response/error envelopes, request IDs, pagination, prototype demo auth, server-side role + institution/region
scope checks, an audit helper (append-only), idempotent seed data, and tests.
Frontend (`frontend/`) is intentionally not created yet.

## Requirements
- Python 3.11+
- Optional: PostgreSQL (default is a local SQLite file, which is enough for development and tests)

## Setup (from a clean checkout)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp ../.env.example ../.env           # optional; defaults work for local dev
python -m app.seed.demo_data --reset # create tables + deterministic synthetic data
uvicorn app.main:app --reload        # http://127.0.0.1:8000/docs
```

Run tests:

```bash
cd backend
pytest -q
```

Try it:

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/demo-login -H 'content-type: application/json' \
  -d '{"email":"institution.user@example.test"}' | python -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
curl -s localhost:8000/api/v1/institutions -H "Authorization: Bearer $TOKEN"
```

### PostgreSQL
Set `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/aicte_ps4` in `.env`, then run the seed
command. Schema is created with `create_all` in Module 0; **Alembic migrations are not set up yet** (see Next steps).

## Demo accounts (synthetic, no passwords — prototype authentication only)

| Role | Email | Scope |
|---|---|---|
| Institution user A | institution.user@example.test | inst_001 only |
| Scrutiny officer | scrutiny.officer@example.test | region reg_central |
| EVC coordinator | evc.coordinator@example.test | region reg_central |
| Compliance officer | compliance.officer@example.test | region reg_central |
| Senior management | management.viewer@example.test | all (read-only by convention) |
| Administrator | admin@example.test | all |
| *Extra:* Institution user B | institution.user.b@example.test | inst_002 only (for cross-institution tests) |
| *Extra:* Regional officer | regional.officer@example.test | region reg_central |
| *Extra:* Committee authority | committee.authority@example.test | region reg_central |

Seed institutions: `inst_001` (reg_central), `inst_002` (reg_west), `inst_003` (reg_central).

## Layout

```
backend/app/core/      config, database, errors, middleware, security, permissions (scope), deps, pagination, enums
backend/app/models/    all shared tables (identity, workflow, compliance, ops)
backend/app/schemas/   Pydantic envelopes and DTOs
backend/app/services/  audit_service (other services arrive with their modules)
backend/app/routers/   health, auth, institutions
backend/app/api/v1/    router registration (later modules add theirs here)
backend/app/seed/      demo_data.py (idempotent)
backend/tests/
docs/                  api-contract.md, architecture.md
```

## Module 0 README snippet
- **Endpoints:** `GET /health`, `POST /auth/demo-login`, `GET /auth/me`, `GET /institutions`, `GET /institutions/{id}` (all under `/api/v1`).
- **Env vars:** `ENVIRONMENT`, `DATABASE_URL`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `DEMO_AUTH_ENABLED`, `CORS_ORIGINS`.
- **Known limitations:** prototype auth (no passwords); no migrations yet; audit append-only is enforced for ORM
  updates/deletes only (also revoke UPDATE/DELETE on `audit_logs` at DB level for production); out-of-scope returns
  403 while non-existent returns 404, so record existence is observable; dashboard/audit-log endpoints belong to later modules.
