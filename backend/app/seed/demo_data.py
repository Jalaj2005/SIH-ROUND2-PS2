"""Deterministic synthetic seed data (Module 0 subset: institutions + demo users).

    python -m app.seed.demo_data            # create tables if missing, upsert seed rows (idempotent)
    python -m app.seed.demo_data --reset    # drop everything, recreate, reseed (refused in production)

All identities are synthetic. Later modules extend this file with applications, compliance items, etc.
"""
import argparse

from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base, get_engine, get_sessionmaker
from app.core.enums import Role
from app.models.identity import Institution, User

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


def seed(db: Session) -> dict[str, int]:
    """Upsert by deterministic primary key; safe to run repeatedly."""
    for row in INSTITUTIONS:
        db.merge(Institution(status="ACTIVE", **row))
    db.flush()
    for row in USERS:
        db.merge(User(is_active=True, **{**row, "role": str(row["role"])}))
    db.commit()
    return {"institutions": len(INSTITUTIONS), "users": len(USERS)}


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
