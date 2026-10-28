"""Deterministic synthetic seed data (institutions, demo users, Module 1 workflow templates + a few demo applications).

    python -m app.seed.demo_data            # create tables if missing, upsert seed rows (idempotent)
    python -m app.seed.demo_data --reset    # drop everything, recreate, reseed (refused in production)

All identities are synthetic. Later modules extend this file with applications, compliance items, etc.
"""
import argparse

from datetime import timedelta

from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base, get_engine, get_sessionmaker
from app.core.enums import Role
from app.core.ids import utcnow
from app.models.identity import Institution, User
from app.models.workflow import Application, ApplicationStageHistory
from app.seed.workflow_templates import NEW_INSTITUTION, EXTENSION_OF_APPROVAL, seed_workflow_templates

INSTITUTIONS = [
    {"id": "inst_001", "name": "Demo Institute of Technology A", "institution_code": "DEMO-0001", "region_id": "reg_central"},
    {"id": "inst_002", "name": "Demo Institute of Management B", "institution_code": "DEMO-0002", "region_id": "reg_west"},
    {"id": "inst_003", "name": "Demo College of Engineering C", "institution_code": "DEMO-0003", "region_id": "reg_central"},
]

USERS = [
    # Appendix A accounts
    {"id": "usr_institution_a", "name": "Institution User (A)", "email": "institution.user@example.test", "role": Role.INSTITUTION_USER, "institution_id": "inst_001", "region_id": "reg_central"},
    {"id": "usr_scrutiny", "name": "Scrutiny Officer", "email": "scrutiny.officer@example.test", "role": Role.SCRUTINY_OFFICER, "institution_id": None, "region_id": "reg_central"},
    {"id": "usr_evc", "name": "EVC Coordinator", "email": "evc.coordinator@example.test", "role": Role.EVC_COORDINATOR, "institution_id": None, "region_id": "reg_central"},
    {"id": "usr_compliance", "name": "Compliance Officer", "email": "compliance.officer@example.test", "role": Role.COMPLIANCE_OFFICER, "institution_id": None, "region_id": "reg_central"},
    {"id": "usr_management", "name": "Senior Management (read-only)", "email": "management.viewer@example.test", "role": Role.SENIOR_MANAGEMENT, "institution_id": None, "region_id": None},
    {"id": "usr_admin", "name": "System Administrator", "email": "admin@example.test", "role": Role.SYSTEM_ADMIN, "institution_id": None, "region_id": None},
    # Extra synthetic accounts (not in Appendix A): needed for cross-institution scope tests and the remaining roles
    {"id": "usr_institution_b", "name": "Institution User (B)", "email": "institution.user.b@example.test", "role": Role.INSTITUTION_USER, "institution_id": "inst_002", "region_id": "reg_west"},
    {"id": "usr_regional", "name": "Regional Officer", "email": "regional.officer@example.test", "role": Role.REGIONAL_OFFICER, "institution_id": None, "region_id": "reg_central"},
    {"id": "usr_committee", "name": "Committee / Competent Authority", "email": "committee.authority@example.test", "role": Role.COMMITTEE_AUTHORITY, "institution_id": None, "region_id": "reg_central"},
]


# Module 1 demo applications (small deterministic set; Module 7 extends with bottleneck / overdue patterns).
# Each: id, number, institution, template, journey of (action, from, to, actor, days_ago, reason, metadata).
_CREATE = ("CREATE", None, "DRAFT", "usr_institution_a")
_SUBMIT = ("SUBMIT", "DRAFT", "SUBMITTED", "usr_institution_a")
_ROUTE = ("ROUTE_TO_SCRUTINY", "SUBMITTED", "IN_SCRUTINY", "usr_institution_a")
_SCR_DONE = ("COMPLETE_SCRUTINY", "IN_SCRUTINY", "EVC_PENDING", "usr_scrutiny")


def _app_specs():
    return [
        # In scrutiny, assigned to the seeded scrutiny officer: the "return with reason" demo case.
        dict(id="app_001", number="APP-2026-0001", inst="inst_001", tmpl=NEW_INSTITUTION, status="IN_SCRUTINY",
             assigned="usr_scrutiny", journey=[(*_CREATE, 10), (*_SUBMIT, 9), (*_ROUTE, 9)]),
        # Already returned with a reason: the "institution resubmits" demo case.
        dict(id="app_002", number="APP-2026-0002", inst="inst_001", tmpl=EXTENSION_OF_APPROVAL,
             status="RETURNED_FOR_DEFICIENCY", assigned=None,
             journey=[(*_CREATE, 12), (*_SUBMIT, 11), (*_ROUTE, 11),
                      ("RETURN_FOR_DEFICIENCY", "IN_SCRUTINY", "RETURNED_FOR_DEFICIENCY", "usr_scrutiny", 6,
                       "Lease document is missing an authorised signature.", {"checklist_code": "LEASE_SIGNATURE"})]),
        # Scrutiny finished, waiting in the EVC queue (Module 5 picks it up).
        dict(id="app_003", number="APP-2026-0003", inst="inst_003", tmpl=NEW_INSTITUTION, status="EVC_PENDING",
             assigned=None, journey=[(*_CREATE, 20), (*_SUBMIT, 19), (*_ROUTE, 19), (*_SCR_DONE, 8)]),
        # Different region (reg_west) and unassigned: out of scope for the central-region officers.
        dict(id="app_004", number="APP-2026-0004", inst="inst_002", tmpl=NEW_INSTITUTION, status="IN_SCRUTINY",
             assigned=None, journey=[(*_CREATE, 5), (*_SUBMIT, 4), (*_ROUTE, 4)]),
        # Draft: visible only to its institution.
        dict(id="app_005", number="APP-2026-0005", inst="inst_001", tmpl=EXTENSION_OF_APPROVAL, status="DRAFT",
             assigned=None, journey=[(*_CREATE, 1)]),
    ]


def seed_applications(db: Session) -> int:
    """Insert-if-missing. Never overwrites: applications move on through the workflow and the stage history is
    append-only, so re-seeding must not rewind a case or touch history rows (use --reset for a clean slate)."""
    now = utcnow()
    created = 0
    for spec in _app_specs():
        if db.get(Application, spec["id"]) is not None:
            continue
        template = spec["tmpl"]
        stage_id = f"stg_{template.key}_{spec['status'].lower()}"
        first_ts = now - timedelta(days=spec["journey"][0][4])
        submitted = next((now - timedelta(days=j[4]) for j in spec["journey"] if j[0] == "SUBMIT"), None)
        db.add(
            Application(
                id=spec["id"], application_number=spec["number"], institution_id=spec["inst"],
                category=template.category, workflow_template_id=template.id, status=spec["status"],
                current_stage_id=stage_id, assigned_to=spec["assigned"], submitted_at=submitted,
                created_at=first_ts, updated_at=now - timedelta(days=spec["journey"][-1][4]),
            )
        )
        db.flush()
        for n, step in enumerate(spec["journey"], start=1):
            action, frm, to, actor, days_ago, *rest = step
            reason, meta = (rest + [None, None])[:2]
            hist_id = f"hist_{spec['id']}_{n}"
            if db.get(ApplicationStageHistory, hist_id) is None:
                db.add(
                    ApplicationStageHistory(
                        id=hist_id, application_id=spec["id"], from_stage=frm, to_stage=to, action=action,
                        reason=reason, actor_id=actor, created_at=now - timedelta(days=days_ago, minutes=-n),
                        metadata_json=meta or None,
                    )
                )
        created += 1
    db.flush()
    return created


def seed(db: Session) -> dict[str, int]:
    """Upsert reference data by deterministic primary key; insert-if-missing for case data. Safe to re-run."""
    for row in INSTITUTIONS:
        db.merge(Institution(status="ACTIVE", **row))
    db.flush()
    for row in USERS:
        db.merge(User(is_active=True, **{**row, "role": str(row["role"])}))
    db.flush()
    templates = seed_workflow_templates(db)
    seed_applications(db)
    db.commit()
    return {"institutions": len(INSTITUTIONS), "users": len(USERS), "workflow_templates": templates,
            "applications": len(_app_specs())}


def reset_schema() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic synthetic demo data.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables first.")
    args = parser.parse_args()

    if args.reset and get_settings().is_production:
        raise SystemExit("Refusing to reset the database when ENVIRONMENT=production.")
    if args.reset:
        reset_schema()
    else:
        Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as db:
        counts = seed(db)
    print(f"Seeded: {counts}")


if __name__ == "__main__":
    main()
