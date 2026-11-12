from datetime import timedelta

from fastapi.testclient import TestClient

from helpers import fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.engine import under_maintenance
from rootfold.graph import resolve
from rootfold.models import Alert, MaintenanceWindow


def test_maintenance_suppresses_alert_and_descendants(
    db, topology, clock: FrozenClock, settings: Settings
) -> None:
    typ, oid = resolve(db, "circuit", "cir-ons-drm-mw")
    now = clock.now()
    db.add(
        MaintenanceWindow(
            object_type=typ,
            object_id=oid,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=2),
            reason="Planned radio swap",
            created_by="admin",
        )
    )
    db.commit()
    assert under_maintenance(db, (typ, oid), now)
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    assert open_incidents(db) == []
    alerts = db.query(Alert).all()
    assert alerts and all(a.suppressed for a in alerts)


def test_alertmanager_and_zabbix_ingest(
    client: TestClient, auth_headers: dict, hook_headers: dict, topology, clock: FrozenClock
) -> None:
    # Import already applied via topology fixture on the same in-memory DB as the app.
    am = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HopDown",
                    "severity": "critical",
                    "circuit": "cir-ons-drm-mw",
                },
                "annotations": {"summary": "Microwave hop down"},
                "fingerprint": "am-hop-1",
                "startsAt": "2026-09-13T04:00:00Z",
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "InstanceDown",
                    "severity": "critical",
                    "instance": "drm-rtr1",
                },
                "annotations": {"summary": "Router unreachable"},
                "fingerprint": "am-rtr-1",
                "startsAt": "2026-09-13T04:00:05Z",
            },
        ],
    }
    r = client.post("/api/ingest/alertmanager", headers=hook_headers, json=am)
    assert r.status_code == 200, r.text
    assert r.json()["suppressed"] == 0
    incidents = client.get("/api/incidents", headers=auth_headers)
    assert incidents.status_code == 200
    rows = incidents.json()
    assert len(rows) == 1
    assert rows[0]["root_slug"] == "cir-ons-drm-mw"
    assert rows[0]["alert_count"] == 2

    zbx = {
        "event_id": "9001",
        "event_value": "1",
        "event_name": "Switch unreachable",
        "host": "drm-sw1",
        "severity": "high",
        "trigger_id": "55",
    }
    z = client.post("/api/ingest/zabbix", headers=hook_headers, json=zbx)
    assert z.status_code == 200, z.text
    detail = client.get(f"/api/incidents/{rows[0]['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["alert_count"] == 3
