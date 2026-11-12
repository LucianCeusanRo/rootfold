from fastapi.testclient import TestClient

from rootfold.clock import FrozenClock
from rootfold.config import Settings


def test_inject_and_reset_lab_scenarios(
    client: TestClient, auth_headers: dict, topology, clock: FrozenClock, settings: Settings
) -> None:
    # Import via fixture already loaded topology; inject a microwave fade.
    r = client.post("/api/lab/inject/microwave_fade", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["scenario"] == "microwave_fade"
    incidents = client.get("/api/incidents", headers=auth_headers).json()
    assert len(incidents) == 1
    assert incidents[0]["root_slug"] == "cir-ons-drm-mw"
    assert incidents[0]["alert_count"] >= 3
    assert "drm" in incidents[0]["blast_radius"]["sites"]

    fiber = client.post("/api/lab/inject/fiber_los", headers=auth_headers)
    assert fiber.status_code == 200
    # Two roots can coexist (microwave + fiber) or the fiber may fold the site
    # symptoms; either way we have at least one open fiber-related incident.
    after = client.get("/api/incidents?status=open", headers=auth_headers).json()
    slugs = {i["root_slug"] for i in after}
    assert "cir-bcu-ons" in slugs or "cir-ons-drm-mw" in slugs

    lacp = client.post("/api/lab/inject/lacp_member", headers=auth_headers)
    assert lacp.status_code == 200
    rows = client.get("/api/incidents", headers=auth_headers).json()
    assert any(i["root_slug"] == "cir-core-east" and i["root_type"] == "circuit" for i in rows)

    reset = client.post("/api/lab/reset", headers=auth_headers)
    assert reset.status_code == 200
    assert client.get("/api/incidents", headers=auth_headers).json() == []

    leftover = client.post("/api/lab/inject/leftover_sweep", headers=auth_headers)
    assert leftover.status_code == 200, leftover.text
    assert leftover.json()["leftover_count"] == 1
    all_ = client.get("/api/incidents", headers=auth_headers).json()
    kinds = {i["kind"]: i for i in all_}
    assert "leftover" in kinds
    assert kinds["leftover"]["status"] == "open"
    parent = next(i for i in all_ if i["kind"] == "outage")
    assert parent["status"] == "resolved"
    assert parent["resolved_by"] == "sweep"


def test_topology_graph_marks_down_nodes(
    client: TestClient, auth_headers: dict, topology, clock: FrozenClock
) -> None:
    client.post("/api/lab/inject/microwave_fade", headers=auth_headers)
    graph = client.get("/api/topology/graph", headers=auth_headers)
    assert graph.status_code == 200, graph.text
    body = graph.json()
    slugs = {n["slug"]: n for n in body["nodes"]}
    assert slugs["cir-ons-drm-mw"]["status"] == "down"
    assert slugs["drm"]["status"] == "down"
    assert slugs["bcu-dc"]["status"] == "up"
    assert any(e["kind"] == "circuit" and e["slug"] == "cir-ons-drm-mw" for e in body["edges"])
