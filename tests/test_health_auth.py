from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["lab_mode"] is True


def test_docs_served(client: TestClient) -> None:
    r = client.get("/api/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower() or "openapi" in r.text.lower()
    spec = client.get("/api/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "Rootfold"


def test_login_and_protected_route(client: TestClient, auth_headers: dict) -> None:
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    denied = client.get("/api/incidents")
    assert denied.status_code == 401
    ok = client.get("/api/incidents", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json() == []


def test_webhook_requires_api_key(client: TestClient, hook_headers: dict) -> None:
    denied = client.post("/api/ingest/generic", json={"name": "x", "status": "firing"})
    assert denied.status_code == 401
    ok = client.post(
        "/api/ingest/generic",
        headers=hook_headers,
        json={"name": "unmapped", "status": "firing", "severity": "warning"},
    )
    assert ok.status_code == 200
    assert len(ok.json()["alerts"]) == 1



def test_operator_ui_served(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Rootfold" in page.text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    css = client.get("/static/app.css")
    assert css.status_code == 200
