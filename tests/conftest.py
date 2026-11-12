from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.importer import import_yaml_path
from rootfold.main import create_app

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "carpathian-carrier.yaml"


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        jwt_secret="test-secret-which-is-long-enough-32b",
        admin_username="admin",
        admin_password="testpass",
        webhook_key="test-webhook-key",
        recovery_sweep_seconds=60,
        sweep_interval_seconds=0,
        lab_mode=True,
    )


@pytest.fixture
def app(settings: Settings, clock: FrozenClock):
    application = create_app(settings=settings, clock=clock, database_url="sqlite:///:memory:")
    return application


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    factory = app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def topology(db):
    stats = import_yaml_path(db, EXAMPLE)
    db.commit()
    return stats


@pytest.fixture
def token(client: TestClient) -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hook_headers() -> dict[str, str]:
    return {"X-API-Key": "test-webhook-key"}



@pytest.fixture
def night_headers(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": "night", "password": "changeme"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
