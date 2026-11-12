from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from helpers import fire, open_incidents
from rootfold.config import Settings
from rootfold.runbooks import attach_runbooks, load_runbooks, score_runbook


def test_library_contains_the_eight_expected_runbooks() -> None:
    ids = {book.id for book in load_runbooks()}
    assert ids == {
        "microwave-fade",
        "fiber-los",
        "lacp-member-down",
        "lacp-bundle-down",
        "high-crc-errors",
        "dns-failure",
        "vpn-tunnel-down",
        "power-site-down",
    }
    microwave = next(b for b in load_runbooks() if b.id == "microwave-fade")
    assert "Ping / ICMP to the far end" in microwave.checks
    assert "RSL" in microwave.body


def test_microwave_incident_gets_the_fade_runbook(
    db: Session, topology, clock, settings: Settings
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    inc = open_incidents(db)[0]
    attached = attach_runbooks(db, inc)
    assert attached, "expected at least one runbook"
    assert attached[0]["id"] == "microwave-fade"
    assert attached[0]["primary"] is True
    fade = next(b for b in load_runbooks() if b.id == "microwave-fade")
    fiber = next(b for b in load_runbooks() if b.id == "fiber-los")
    assert score_runbook(fade, inc, db) > score_runbook(fiber, inc, db)


def test_fiber_and_lacp_member_matching(db: Session, topology, clock, settings: Settings) -> None:
    fire(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    fiber_inc = open_incidents(db)[0]
    fiber_ids = [b["id"] for b in attach_runbooks(db, fiber_inc)]
    assert fiber_ids[0] == "fiber-los"

    fire(db, clock, settings, "cir-core-east", "circuit", "East member down")
    member = [i for i in open_incidents(db) if i.id != fiber_inc.id][0]
    member_ids = [b["id"] for b in attach_runbooks(db, member)]
    assert member_ids[0] == "lacp-member-down"


def test_ticking_runbook_checks_feeds_the_gate(
    client: TestClient, auth_headers: dict, db: Session, topology, clock, settings: Settings
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    inc = open_incidents(db)[0]
    db.commit()

    listed = client.get(f"/api/incidents/{inc.id}/runbooks", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["runbooks"][0]["id"] == "microwave-fade"
    checks = listed.json()["runbooks"][0]["checks"]
    assert checks

    tick = client.post(
        f"/api/incidents/{inc.id}/checks",
        headers=auth_headers,
        json={"checks": [checks[0], checks[1]]},
    )
    assert tick.status_code == 200, tick.text
    assert checks[0] in tick.json()["checks"]
    assert tick.json()["gate_complete"] is False

    # Completing the remaining gate fields now works because checks are already present.
    gate = client.put(
        f"/api/incidents/{inc.id}/gate",
        headers=auth_headers,
        json={
            "impact": "site-down",
            "urgency": "high",
            "checks": tick.json()["checks"],
            "notes": "RSL dropped; maintenance calendar is clear.",
        },
    )
    assert gate.status_code == 200, gate.text
    assert gate.json()["gate_complete"] is True
    kinds = [e["kind"] for e in gate.json()["timeline"]]
    assert "check" in kinds and "gate" in kinds


def test_runbook_collection_endpoint(client: TestClient, auth_headers: dict) -> None:
    r = client.get("/api/runbooks", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 8
    one = client.get("/api/runbooks/dns-failure", headers=auth_headers)
    assert one.status_code == 200
    assert "dig" in one.json()["body"]
    missing = client.get("/api/runbooks/not-a-book", headers=auth_headers)
    assert missing.status_code == 404
