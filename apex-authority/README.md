# Apex Authority — Module 2 (AI Instructor Copilot)

Scenario drafting, After-Action Review (AAR) generation, Gemini provider abstraction, review and PDF export.
Module 1 (simulation core) is developed separately; Module 2 runs against fixtures until it lands.

## Run Module 2 locally (no Gemini key needed)
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # never commit .env
APP_ENV=development AI_PROVIDER=mock python3 -m uvicorn app.main:app --port 8000
python3 -m pytest -q                       # full suite; no network, no paid calls
python3 scripts/export_schemas.py          # regenerate docs/*.schema.json + openapi.json
```
Dev auth headers: `X-Demo-User-Id: <uuid>`, `X-Demo-Role: instructor`. Sample session for AAR:
`9d47c8ce-6ca5-5e2c-8717-2f37738fe9b2`.

## Using real Gemini
Set `AI_PROVIDER=gemini`, `GEMINI_API_KEY` and `GEMINI_MODEL` (confirm a currently supported model name in Google's
documentation) in the backend environment only. Without them the AI endpoints return `503 AI_NOT_CONFIGURED`.

See `docs/api-contract.md` for the decisions that need Module 1's confirmation.
