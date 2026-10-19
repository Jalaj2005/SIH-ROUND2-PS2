"""Regenerate docs/*.schema.json and docs/openapi.json from the Pydantic models.
Run from backend/:  python scripts/export_schemas.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import create_app
from app.schemas.aar import AARInput, AARReport
from app.schemas.scenario import Scenario

DOCS = Path(__file__).resolve().parents[2] / "docs"
DOCS.mkdir(exist_ok=True)
for name, model in (("scenario", Scenario), ("aar-input", AARInput), ("aar-output", AARReport)):
    (DOCS / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
(DOCS / "openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
print("wrote", sorted(p.name for p in DOCS.glob("*.json")))
