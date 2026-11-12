from pathlib import Path

from fastapi.testclient import TestClient

from rootfold.graph import blast_radius, resolve

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "carpathian-carrier.yaml"


def test_import_example_counts(topology: dict) -> None:
    assert topology["sites"] == 11
    assert topology["devices"] >= 15
    assert topology["circuits"] >= 10
    assert topology["bundles"] == 1
    assert topology["dependencies"] >= 10


def test_import_via_api(client: TestClient, auth_headers: dict) -> None:
    raw = EXAMPLE.read_text(encoding="utf-8")
    r = client.post(
        "/api/topology/import",
        headers=auth_headers,
        json={"yaml": raw},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sites"] == 11
    sites = client.get("/api/topology/sites", headers=auth_headers)
    slugs = {s["slug"] for s in sites.json()}
    assert {"bcu-dc", "drm", "cms", "bcz"} <= slugs


def test_blast_radius_microwave_includes_behind_sites(db, topology) -> None:
    typ, oid = resolve(db, "circuit", "cir-ons-drm-mw")
    radius = blast_radius(db, typ, oid)
    assert "drm" in radius["sites"]
    assert "cms" in radius["sites"]  # Comănești sits behind Dărmănești
    assert "drm-backup" in radius["devices"]
    assert "cir-drm-customer" in radius["circuits"]
    assert "Forestworks SRL" in radius["customers"]
    # The core should not be in the blast radius of a last-mile hop.
    assert "bcu-dc" not in radius["sites"]
