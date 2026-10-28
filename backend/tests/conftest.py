import os

# Must be set before the app is imported (settings are cached).
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789-abcdefghijklmnop"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DEMO_AUTH_ENABLED"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.database import Base, get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed.demo_data import seed  # noqa: E402


@pytest.fixture()
def engine():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        seed(s)
    return factory


@pytest.fixture()
def db_session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture()
def app(session_factory):
    application = create_app()

    def _get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def login(client):
    """login(email) -> Authorization headers for a seeded demo user."""

    def _login(email: str) -> dict:
        r = client.post("/api/v1/auth/demo-login", json={"email": email})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    return _login
