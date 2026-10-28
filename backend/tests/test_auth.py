import time

import jwt
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models.identity import User
from app.models.ops import AuditLog


def test_demo_login_returns_token_user_and_scope(client):
    r = client.post("/api/v1/auth/demo-login", json={"email": "Institution.User@example.test"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["token_type"] == "bearer" and data["access_token"]
    assert data["user"]["role"] == "INSTITUTION_USER"
    assert data["scope"] == {"scope_type": "INSTITUTION", "institution_id": "inst_001", "region_id": "reg_central"}
    assert data["prototype_auth"] is True


def test_unknown_user_rejected(client):
    r = client.post("/api/v1/auth/demo-login", json={"email": "nobody@example.test"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_demo_login_can_be_disabled(app, client):
    base = get_settings()
    disabled = Settings(**{**base.__dict__, "demo_auth_enabled": False})
    app.dependency_overrides[get_settings] = lambda: disabled
    r = client.post("/api/v1/auth/demo-login", json={"email": "admin@example.test"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "DEMO_AUTH_DISABLED"


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_returns_role_and_scope(client, login):
    r = client.get("/api/v1/auth/me", headers=login("scrutiny.officer@example.test"))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["user"]["role"] == "SCRUTINY_OFFICER"
    assert data["scope"]["scope_type"] == "REGION" and data["scope"]["region_id"] == "reg_central"


def test_garbage_and_forged_tokens_rejected(client):
    bad = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_TOKEN"

    forged = jwt.encode({"sub": "usr_admin", "exp": int(time.time()) + 600}, "x" * 40, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_token_rejected(client):
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "usr_admin", "iat": now - 100, "exp": now - 10}, get_settings().secret_key, algorithm="HS256"
    )
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_token_for_deactivated_user_rejected(client, login, session_factory):
    headers = login("admin@example.test")
    with session_factory() as s:
        s.get(User, "usr_admin").is_active = False
        s.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_login_attempts_are_audited(client, session_factory):
    client.post("/api/v1/auth/demo-login", json={"email": "admin@example.test"})
    client.post("/api/v1/auth/demo-login", json={"email": "nobody@example.test"})
    with session_factory() as s:
        actions = set(s.scalars(select(AuditLog.action)))
    assert {"AUTH_DEMO_LOGIN", "AUTH_DEMO_LOGIN_FAILED"} <= actions
