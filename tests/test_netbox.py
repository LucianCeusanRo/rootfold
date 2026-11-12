from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rootfold.config import Settings
from rootfold.models import Circuit, Device, Site
from rootfold.netbox import (
    NetBoxError,
    fetch_inventory,
    import_from_fixture,
    import_from_netbox,
    map_inventory,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "netbox.json"


def test_fixture_maps_sites_devices_circuits_and_skips_same_site_cable() -> None:
    raw = json.loads(FIXTURE.read_text())
    pages = raw["pages"]
    inventory = {
        "sites": pages["/api/dcim/sites/"]["results"],
        "devices": pages["/api/dcim/devices/"]["results"],
        "cables": pages["/api/dcim/cables/"]["results"],
        "circuits": pages["/api/circuits/circuits/"]["results"],
    }
    payload = map_inventory(inventory)
    slugs = {s["slug"] for s in payload["sites"]}
    assert slugs == {"bcu-pop", "ons", "drm"}
    devices = {d["slug"]: d for d in payload["devices"]}
    assert devices["ons-rtr-1"]["vendor"] == "Juniper"
    assert devices["ons-rtr-1"]["management_ip"] == "10.0.2.1"
    assert devices["drm-sw-1"]["role"] == "switch"
    circuits = {c["slug"]: c for c in payload["circuits"]}
    assert "cir-bcu-ons" in circuits
    assert circuits["cir-bcu-ons"]["media"] == "fiber"
    assert circuits["cir-ons-drm-mw"]["media"] == "microwave"
    assert circuits["cir-ons-drm-mw"]["capacity_mbps"] == 200
    assert circuits["cir-drm-customer"]["customer"] == "Forestworks SRL"
    assert "drm-internal-patch" not in circuits
    assert payload["_meta"]["cables_skipped_same_site"] == 1


def test_import_from_fixture_upserts(db: Session) -> None:
    stats = import_from_fixture(db, FIXTURE)
    db.commit()
    assert stats["sites"] == 3
    assert stats["devices"] == 4
    assert stats["circuits"] == 3  # fiber cable + mw circuit + customer tail
    assert stats["cables_skipped_same_site"] == 1
    assert stats["source"] == "netbox-fixture"
    assert db.query(Site).count() == 3
    assert db.query(Device).count() == 4
    mw = db.query(Circuit).filter(Circuit.slug == "cir-ons-drm-mw").one()
    assert mw.media == "microwave"
    assert mw.a_device_id is not None
    # Second import is an upsert, not a duplicate.
    again = import_from_fixture(db, FIXTURE)
    db.commit()
    assert db.query(Site).count() == 3
    assert again["sites"] == 3


def test_fetch_inventory_uses_token_and_recorded_pages() -> None:
    recorded = json.loads(FIXTURE.read_text())["pages"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Token lab-netbox-token"
        path = request.url.path
        if not path.endswith("/"):
            path += "/"
        return httpx.Response(200, json=recorded[path])

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://netbox.lab.example",
        headers={"Authorization": "Token lab-netbox-token"},
    )
    inventory = fetch_inventory(
        "https://netbox.lab.example", "lab-netbox-token", client=client
    )
    assert len(inventory["sites"]) == 3
    assert len(inventory["cables"]) == 2


def test_fetch_inventory_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://netbox.lab.example",
    )
    try:
        fetch_inventory("https://netbox.lab.example", "bad", client=client)
        raise AssertionError("expected NetBoxError")
    except NetBoxError as exc:
        assert "401" in str(exc)


def test_api_import_netbox_requires_config(client: TestClient, auth_headers: dict) -> None:
    r = client.post("/api/topology/import-netbox", headers=auth_headers)
    assert r.status_code == 400
    assert "NETBOX" in r.json()["detail"]


def test_api_import_netbox_from_lab_fixture(
    client: TestClient, auth_headers: dict, db: Session
) -> None:
    r = client.post(
        "/api/topology/import-netbox",
        headers=auth_headers,
        params={"fixture": str(FIXTURE)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sites"] == 3
    assert body["source"] == "netbox-fixture"
    assert db.query(Site).count() == 3


def test_import_from_netbox_honours_settings_fixture(db: Session, settings: Settings) -> None:
    settings.netbox_fixture = str(FIXTURE)
    stats = import_from_netbox(db, settings)
    assert stats["devices"] == 4
