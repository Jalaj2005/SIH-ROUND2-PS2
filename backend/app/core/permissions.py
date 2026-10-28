"""Role and record-scope rules, enforced on the server.

Institution scope (Module 0 rule, reused by later modules):
  INSTITUTION_USER              -> only users.institution_id
  region-scoped officer roles   -> institutions whose region_id == users.region_id (no region => nothing)
  SENIOR_MANAGEMENT, SYSTEM_ADMIN -> all institutions (management is read-only by convention)
  anything else / unknown role  -> nothing (fail closed)

Per-record rules (e.g. "assigned cases only") belong to the module that owns the record.
"""
from sqlalchemy import ColumnElement, false, select, true
from sqlalchemy.orm import Session

from app.core.enums import Role, ScopeType
from app.core.errors import forbidden, not_found
from app.models.identity import Institution, User

UNRESTRICTED_ROLES = frozenset({Role.SENIOR_MANAGEMENT, Role.SYSTEM_ADMIN})
REGION_SCOPED_ROLES = frozenset(
    {
        Role.SCRUTINY_OFFICER,
        Role.REGIONAL_OFFICER,
        Role.EVC_COORDINATOR,
        Role.COMPLIANCE_OFFICER,
        Role.COMMITTEE_AUTHORITY,
    }
)


def parse_role(user: User) -> Role | None:
    try:
        return Role(user.role)
    except ValueError:
        return None


def describe_scope(user: User) -> dict:
    role = parse_role(user)
    if role == Role.INSTITUTION_USER and user.institution_id:
        return {"scope_type": ScopeType.INSTITUTION, "institution_id": user.institution_id, "region_id": user.region_id}
    if role in UNRESTRICTED_ROLES:
        return {"scope_type": ScopeType.ALL, "institution_id": None, "region_id": None}
    if role in REGION_SCOPED_ROLES and user.region_id:
        return {"scope_type": ScopeType.REGION, "institution_id": None, "region_id": user.region_id}
    return {"scope_type": ScopeType.NONE, "institution_id": None, "region_id": None}


def institution_scope_clause(user: User) -> ColumnElement[bool]:
    """WHERE-clause over the Institution table for the institutions this user may see."""
    scope = describe_scope(user)
    kind = scope["scope_type"]
    if kind == ScopeType.INSTITUTION:
        return Institution.id == scope["institution_id"]
    if kind == ScopeType.REGION:
        return Institution.region_id == scope["region_id"]
    if kind == ScopeType.ALL:
        return true()
    return false()


def institution_id_in_scope(user: User, column) -> ColumnElement[bool]:
    """Scope any table that has an institution_id column, e.g.
    select(Application).where(institution_id_in_scope(user, Application.institution_id))."""
    return column.in_(select(Institution.id).where(institution_scope_clause(user)))


def can_access_institution(db: Session, user: User, institution_id: str) -> bool:
    found = db.scalar(select(Institution.id).where(Institution.id == institution_id, institution_scope_clause(user)))
    return found is not None


def get_institution_in_scope(db: Session, user: User, institution_id: str) -> Institution:
    """404 if the institution does not exist, 403 if it exists but is outside the user's scope."""
    institution = db.get(Institution, institution_id)
    if institution is None:
        raise not_found("Institution not found.")
    if not can_access_institution(db, user, institution_id):
        raise forbidden("This record is outside your authorised scope.")
    return institution
