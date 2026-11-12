from fastapi.testclient import TestClient

from helpers import clear, fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.engine import run_due_sweeps
from rootfold.models import Incident

COMPLETE = {
    "impact": "site-down",
    "urgency": "high",
    "checks": ["ping uplink", "checked maintenance calendar"],
    "notes": "Microwave hop is down; site Dărmănești is unreachable.",
}


def _open_one(db, clock, settings) -> Incident:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    return open_incidents(db)[0]


def test_resolve_and_escalate_blocked_until_gate_complete(
    client: TestClient, auth_headers: dict, db, topology, clock: FrozenClock, settings: Settings
) -> None:
    inc = _open_one(db, clock, settings)
    db.commit()
    blocked = client.post(f"/api/incidents/{inc.id}/resolve", headers=auth_headers)
    assert blocked.status_code == 422, blocked.text
    body = blocked.json()["detail"]
    assert set(body["missing"]) == {"impact", "urgency", "checks", "notes"}

    blocked_e = client.post(f"/api/incidents/{inc.id}/escalate", headers=auth_headers)
    assert blocked_e.status_code == 422

    partial = client.put(
        f"/api/incidents/{inc.id}/gate",
        headers=auth_headers,
        json={"impact": "site-down", "urgency": "high", "checks": [], "notes": "too short"},
    )
    assert partial.status_code == 422
    assert set(partial.json()["detail"]["missing"]) == {"checks", "notes"}

    ok = client.put(f"/api/incidents/{inc.id}/gate", headers=auth_headers, json=COMPLETE)
    assert ok.status_code == 200, ok.text
    assert ok.json()["gate_complete"] is True
    assert ok.json()["gate_completed_by"] == "admin"
    kinds = [e["kind"] for e in ok.json()["timeline"]]
    assert "opened" in kinds and "gate" in kinds

    esc = client.post(f"/api/incidents/{inc.id}/escalate", headers=auth_headers)
    assert esc.status_code == 200, esc.text
    assert esc.json()["status"] == "escalated"
    assert esc.json()["escalated_by"] == "admin"

    again = client.post(f"/api/incidents/{inc.id}/escalate", headers=auth_headers)
    assert again.status_code == 422

    nxt = client.post(f"/api/incidents/{inc.id}/resolve", headers=auth_headers)
    assert nxt.status_code == 200
    assert nxt.json()["status"] == "resolved"
    assert nxt.json()["resolved_by"] == "admin"


def test_sweep_auto_resolve_does_not_require_the_gate(
    db, topology, clock: FrozenClock, settings: Settings
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    clock.advance(5)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clock.advance(settings.recovery_sweep_seconds)
    clear(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    leftovers = run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    assert leftovers == []
    parent = db.query(Incident).one()
    assert parent.status == "resolved"
    assert parent.resolved_by == "sweep"
    assert parent.gate_completed_at is None
