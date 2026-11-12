from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from helpers import fire, open_incidents
from rootfold.config import Settings
from rootfold.exporters import (
    ExportError,
    build_jira_payload,
    build_snow_payload,
    export_incident,
    jira_configured,
)
from rootfold.models import TicketExport


def _inc(db, clock, settings):
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    inc = open_incidents(db)[0]
    inc.impact = "site-down"
    inc.urgency = "high"
    inc.checks = ["Ping / ICMP to the far end"]
    inc.l1_notes = "Last-mile radio hop is down; Dărmănești is unreachable."
    db.flush()
    return inc


def test_payloads_include_ref_and_blast_radius(db: Session, topology, clock, settings: Settings) -> None:
    inc = _inc(db, clock, settings)
    jira = build_jira_payload(db, inc, settings)
    assert jira["fields"]["project"]["key"] == "NOC"
    assert jira["fields"]["issuetype"]["name"] == "Incident"
    assert inc.public_ref in jira["fields"]["summary"]
    assert jira["fields"]["description"]["type"] == "doc"
    assert jira["fields"]["priority"]["name"] == "High"
    snow = build_snow_payload(db, inc, settings)
    assert snow["short_description"].startswith(inc.public_ref)
    assert snow["impact"] == "1"
    assert snow["urgency"] == "1"
    assert "Dărmănești" in snow["description"] or "drm" in snow["description"]


def test_unconfigured_export_is_dry_run_only(
    db: Session, topology, clock, settings: Settings
) -> None:
    inc = _inc(db, clock, settings)
    assert jira_configured(settings) is False
    row = export_incident(
        db, inc, settings, "jira", actor="admin", now=clock.now(), dry_run=None
    )
    assert row.dry_run is True
    assert row.status == "preview"
    assert row.external_key is None
    try:
        export_incident(
            db, inc, settings, "jira", actor="admin", now=clock.now(), dry_run=False
        )
        raise AssertionError("expected ExportError")
    except ExportError as exc:
        assert "not configured" in str(exc)


def test_jira_send_is_mocked(db: Session, topology, clock, settings: Settings) -> None:
    inc = _inc(db, clock, settings)
    settings.jira_url = "https://example.atlassian.net"
    settings.jira_user = "noc@example.com"
    settings.jira_token = "jira-token"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        body = request.read()
        seen["body"] = body
        assert request.url.path == "/rest/api/3/issue"
        return httpx.Response(
            201,
            json={"id": "10001", "key": "NOC-42", "self": "https://example.atlassian.net/rest/api/3/issue/10001"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    row = export_incident(
        db,
        inc,
        settings,
        "jira",
        actor="admin",
        now=clock.now(),
        dry_run=False,
        client=client,
    )
    assert row.status == "sent"
    assert row.external_key == "NOC-42"
    assert seen["auth"].startswith("Basic ")
    assert inc.public_ref.encode() in seen["body"]


def test_servicenow_send_is_mocked(db: Session, topology, clock, settings: Settings) -> None:
    inc = _inc(db, clock, settings)
    settings.snow_url = "https://example.service-now.com"
    settings.snow_user = "integr.user"
    settings.snow_password = "snow-pass"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        assert request.url.path == "/api/now/table/incident"
        return httpx.Response(
            201,
            json={"result": {"sys_id": "abc123", "number": "INC0012345"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    row = export_incident(
        db,
        inc,
        settings,
        "servicenow",
        actor="admin",
        now=clock.now(),
        dry_run=False,
        client=client,
    )
    assert row.external_key == "INC0012345"
    assert "sys_id=abc123" in (row.url or "")


def test_api_export_dry_run_when_not_configured(
    client: TestClient, auth_headers: dict, db: Session, topology, clock, settings: Settings
) -> None:
    inc = _inc(db, clock, settings)
    db.commit()
    status = client.get(f"/api/incidents/{inc.id}/export", headers=auth_headers)
    assert status.status_code == 200, status.text
    assert status.json()["jira_configured"] is False
    assert status.json()["servicenow_configured"] is False

    preview = client.post(
        f"/api/incidents/{inc.id}/export",
        headers=auth_headers,
        json={"backend": "jira"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True
    assert body["payload"]["fields"]["project"]["key"] == "NOC"

    blocked = client.post(
        f"/api/incidents/{inc.id}/export",
        headers=auth_headers,
        json={"backend": "servicenow", "dry_run": False},
    )
    assert blocked.status_code == 422
    assert db.query(TicketExport).count() == 1
