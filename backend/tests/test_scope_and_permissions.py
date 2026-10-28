from app.core.enums import Role
from app.core.deps import require_roles
from app.core.permissions import can_access_institution, institution_scope_clause
from app.models.identity import Institution, User
from sqlalchemy import select

A, B, C = "inst_001", "inst_002", "inst_003"
INST_USER_A = "institution.user@example.test"
INST_USER_B = "institution.user.b@example.test"


def test_institution_user_reads_own_institution(client, login):
    r = client.get(f"/api/v1/institutions/{A}", headers=login(INST_USER_A))
    assert r.status_code == 200
    assert r.json()["data"]["id"] == A


def test_institution_user_cannot_read_another_institution_by_changing_id(client, login):
    r = client.get(f"/api/v1/institutions/{B}", headers=login(INST_USER_A))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    assert "Demo Institute of Management B" not in r.text  # no data leaks through the error

    reverse = client.get(f"/api/v1/institutions/{A}", headers=login(INST_USER_B))
    assert reverse.status_code == 403


def test_institution_list_is_scoped(client, login):
    r = client.get("/api/v1/institutions", headers=login(INST_USER_A))
    body = r.json()
    assert [i["id"] for i in body["data"]] == [A]
    assert body["meta"]["total"] == 1


def test_region_scoped_officer_sees_only_region(client, login):
    h = login("scrutiny.officer@example.test")
    ids = {i["id"] for i in client.get("/api/v1/institutions", headers=h).json()["data"]}
    assert ids == {A, C}
    assert client.get(f"/api/v1/institutions/{C}", headers=h).status_code == 200
    assert client.get(f"/api/v1/institutions/{B}", headers=h).status_code == 403


def test_management_and_admin_see_everything(client, login):
    for email in ("management.viewer@example.test", "admin@example.test"):
        body = client.get("/api/v1/institutions", headers=login(email)).json()
        assert {i["id"] for i in body["data"]} == {A, B, C}


def test_missing_institution_is_404_and_unauthenticated_is_401(client, login):
    assert client.get("/api/v1/institutions/inst_nope", headers=login("admin@example.test")).status_code == 404
    assert client.get(f"/api/v1/institutions/{A}").status_code == 401
    assert client.get("/api/v1/institutions").status_code == 401


def test_status_filter(client, login):
    h = login("admin@example.test")
    assert client.get("/api/v1/institutions?status=ACTIVE", headers=h).json()["meta"]["total"] == 3
    assert client.get("/api/v1/institutions?status=SUSPENDED", headers=h).json()["meta"]["total"] == 0


def test_scope_fails_closed_without_institution_or_region(db_session):
    orphan_inst_user = User(id="u1", name="x", email="x@example.test", role=Role.INSTITUTION_USER, institution_id=None)
    orphan_officer = User(id="u2", name="y", email="y@example.test", role=Role.SCRUTINY_OFFICER, region_id=None)
    unknown_role = User(id="u3", name="z", email="z@example.test", role="SUPERUSER")
    for user in (orphan_inst_user, orphan_officer, unknown_role):
        rows = db_session.scalars(select(Institution).where(institution_scope_clause(user))).all()
        assert rows == []
        assert can_access_institution(db_session, user, A) is False


def test_require_roles_dependency(app, client, login):
    from fastapi import Depends

    @app.get("/__admin-only")
    def admin_only(user: User = Depends(require_roles(Role.SYSTEM_ADMIN))):
        return {"ok": True}

    assert client.get("/__admin-only", headers=login("admin@example.test")).status_code == 200
    r = client.get("/__admin-only", headers=login(INST_USER_A))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert client.get("/__admin-only").status_code == 401


def test_pagination_defaults_limits_and_bounds(client, login):
    h = login("admin@example.test")
    first = client.get("/api/v1/institutions?page_size=2", headers=h).json()
    assert len(first["data"]) == 2
    assert first["meta"] | {"request_id": None} == {"request_id": None, "page": 1, "page_size": 2, "total": 3}
    assert len(client.get("/api/v1/institutions?page_size=2&page=2", headers=h).json()["data"]) == 1
    assert client.get("/api/v1/institutions?page=9", headers=h).json()["data"] == []
    default = client.get("/api/v1/institutions", headers=h).json()["meta"]
    assert default["page"] == 1 and default["page_size"] == 20

    for bad in ("page_size=101", "page_size=0", "page=0"):
        r = client.get(f"/api/v1/institutions?{bad}", headers=h)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
