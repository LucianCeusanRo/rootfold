from fastapi.testclient import TestClient

from helpers import fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings


def test_handover_snapshot_requires_incoming_ack(
    client: TestClient,
    auth_headers: dict,
    night_headers: dict,
    db,
    topology,
    clock: FrozenClock,
    settings: Settings,
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "cir-core-east", "circuit", "East member down")
    db.commit()
    assert len(open_incidents(db)) == 2

    empty = client.get("/api/handover/pending", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json() is None

    closed = client.post(
        "/api/handover/close",
        headers=auth_headers,
        json={"notes": "Microwave last-mile still down; leftover sweep not run yet."},
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "pending_ack"
    assert body["created_by"] == "admin"
    assert body["pending"] is True
    assert body["snapshot"]["count"] == 2
    refs = {i["public_ref"] for i in body["snapshot"]["incidents"]}
    assert len(refs) == 2

    # Cannot close another shift while one is waiting for ack.
    again = client.post("/api/handover/close", headers=auth_headers, json={})
    assert again.status_code == 409

    pending = client.get("/api/handover/pending", headers=night_headers)
    assert pending.status_code == 200
    assert pending.json()["id"] == body["id"]

    acked = client.post(
        f"/api/handover/{body['id']}/ack",
        headers=night_headers,
        json={"notes": "Night shift has the microwave incident."},
    )
    assert acked.status_code == 200, acked.text
    assert acked.json()["status"] == "acked"
    assert acked.json()["acked_by"] == "night"
    assert acked.json()["pending"] is False

    twice = client.post(f"/api/handover/{body['id']}/ack", headers=night_headers, json={})
    assert twice.status_code == 409

    assert client.get("/api/handover/pending", headers=auth_headers).json() is None
    # A new close is allowed after ack.
    nxt = client.post("/api/handover/close", headers=night_headers, json={"notes": "Quiet so far."})
    assert nxt.status_code == 200
    assert nxt.json()["created_by"] == "night"
