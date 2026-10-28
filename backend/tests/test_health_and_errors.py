from fastapi.testclient import TestClient


def test_health_ok_and_non_sensitive(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "ok"
    assert set(body["data"]) == {"status", "service", "version", "database"}
    assert body["meta"]["request_id"]
    assert r.headers["x-request-id"] == body["meta"]["request_id"]


def test_client_supplied_request_id_is_echoed(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "req_custom-1"})
    assert r.headers["x-request-id"] == "req_custom-1"
    assert r.json()["meta"]["request_id"] == "req_custom-1"


def test_malformed_request_id_is_replaced(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "bad id with spaces!"})
    assert r.headers["x-request-id"].startswith("req_")


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert err["request_id"] == r.headers["x-request-id"]


def test_validation_error_envelope(client):
    r = client.post("/api/v1/auth/demo-login", json={})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"][0]["field"] == "email"


def test_unhandled_exception_returns_500_envelope(app):
    @app.get("/__boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in r.text


def test_openapi_exposes_foundation_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/health",
        "/api/v1/auth/demo-login",
        "/api/v1/auth/me",
        "/api/v1/institutions",
        "/api/v1/institutions/{institution_id}",
    ):
        assert path in paths
