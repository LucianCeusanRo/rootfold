"""YAML / CSV topology import. Objects are upserted by slug."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from rootfold.models import Bundle, BundleMember, Circuit, Dependency, Device, Site


def _read_yaml(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML topology must be a mapping")
    return data


def import_yaml_text(db: Session, text: str) -> dict[str, int]:
    return import_payload(db, _read_yaml(text))


def import_yaml_path(db: Session, path: Path) -> dict[str, int]:
    return import_yaml_text(db, path.read_text(encoding="utf-8"))


def _upsert_site(db: Session, item: dict) -> Site:
    row = db.query(Site).filter(Site.slug == item["slug"]).one_or_none()
    if row is None:
        row = Site(slug=item["slug"])
        db.add(row)
    row.name = item.get("name") or item["slug"]
    row.region = item.get("region")
    row.notes = item.get("notes")
    db.flush()
    return row


def _upsert_device(db: Session, item: dict, sites: dict[str, Site]) -> Device:
    site_slug = item["site"]
    if site_slug not in sites:
        raise ValueError(f"Device {item.get('slug')} references unknown site {site_slug}")
    row = db.query(Device).filter(Device.slug == item["slug"]).one_or_none()
    if row is None:
        row = Device(slug=item["slug"])
        db.add(row)
    row.name = item.get("name") or item["slug"]
    row.role = item.get("role") or "device"
    row.site_id = sites[site_slug].id
    row.management_ip = item.get("management_ip")
    row.vendor = item.get("vendor")
    row.model = item.get("model")
    db.flush()
    return row


def _upsert_circuit(
    db: Session, item: dict, sites: dict[str, Site], devices: dict[str, Device]
) -> Circuit:
    for key in ("a_site", "z_site"):
        if item[key] not in sites:
            raise ValueError(f"Circuit {item.get('slug')} references unknown site {item[key]}")
    row = db.query(Circuit).filter(Circuit.slug == item["slug"]).one_or_none()
    if row is None:
        row = Circuit(slug=item["slug"])
        db.add(row)
    row.name = item.get("name") or item["slug"]
    row.media = item.get("media") or "fiber"
    row.a_site_id = sites[item["a_site"]].id
    row.z_site_id = sites[item["z_site"]].id
    a_dev, z_dev = item.get("a_device"), item.get("z_device")
    if a_dev and a_dev not in devices:
        raise ValueError(f"Circuit {item['slug']} references unknown device {a_dev}")
    if z_dev and z_dev not in devices:
        raise ValueError(f"Circuit {item['slug']} references unknown device {z_dev}")
    row.a_device_id = devices[a_dev].id if a_dev else None
    row.z_device_id = devices[z_dev].id if z_dev else None
    row.capacity_mbps = item.get("capacity_mbps")
    row.customer = item.get("customer")
    row.vendor_circuit_id = item.get("vendor_circuit_id")
    db.flush()
    return row


def _upsert_bundle(db: Session, item: dict, devices: dict[str, Device], circuits: dict[str, Circuit]) -> Bundle:
    if item["device"] not in devices:
        raise ValueError(f"Bundle {item.get('slug')} references unknown device {item['device']}")
    row = db.query(Bundle).filter(Bundle.slug == item["slug"]).one_or_none()
    if row is None:
        row = Bundle(slug=item["slug"])
        db.add(row)
    row.name = item.get("name") or item["slug"]
    row.device_id = devices[item["device"]].id
    db.flush()
    db.query(BundleMember).filter(BundleMember.bundle_id == row.id).delete()
    for member in item.get("members") or []:
        if member not in circuits:
            raise ValueError(f"Bundle {item['slug']} references unknown circuit {member}")
        db.add(BundleMember(bundle_id=row.id, circuit_id=circuits[member].id))
    db.flush()
    return row


def _upsert_dep(db: Session, item: dict, index: dict[str, dict[str, int]]) -> Dependency:
    parent = item["parent"]
    child = item["child"]
    ptype, pslug = parent["type"], parent["slug"]
    ctype, cslug = child["type"], child["slug"]
    if pslug not in index.get(ptype, {}):
        raise ValueError(f"Dependency parent {ptype}:{pslug} not found")
    if cslug not in index.get(ctype, {}):
        raise ValueError(f"Dependency child {ctype}:{cslug} not found")
    pid, cid = index[ptype][pslug], index[ctype][cslug]
    row = (
        db.query(Dependency)
        .filter(
            Dependency.parent_type == ptype,
            Dependency.parent_id == pid,
            Dependency.child_type == ctype,
            Dependency.child_id == cid,
        )
        .one_or_none()
    )
    if row is None:
        row = Dependency(parent_type=ptype, parent_id=pid, child_type=ctype, child_id=cid)
        db.add(row)
        db.flush()
    return row


def import_payload(db: Session, data: dict[str, Any]) -> dict[str, int]:
    sites = {s.slug: s for s in (_upsert_site(db, i) for i in data.get("sites") or [])}
    # Include sites that already existed.
    sites.update({s.slug: s for s in db.query(Site).all()})
    devices = {d.slug: d for d in (_upsert_device(db, i, sites) for i in data.get("devices") or [])}
    devices.update({d.slug: d for d in db.query(Device).all()})
    circuits = {
        c.slug: c for c in (_upsert_circuit(db, i, sites, devices) for i in data.get("circuits") or [])
    }
    circuits.update({c.slug: c for c in db.query(Circuit).all()})
    bundles = {
        b.slug: b
        for b in (_upsert_bundle(db, i, devices, circuits) for i in data.get("bundles") or [])
    }
    bundles.update({b.slug: b for b in db.query(Bundle).all()})
    index = {
        "site": {k: v.id for k, v in sites.items()},
        "device": {k: v.id for k, v in devices.items()},
        "circuit": {k: v.id for k, v in circuits.items()},
        "bundle": {k: v.id for k, v in bundles.items()},
    }
    deps = [_upsert_dep(db, i, index) for i in data.get("dependencies") or []]
    db.flush()
    return {
        "sites": len(data.get("sites") or []),
        "devices": len(data.get("devices") or []),
        "circuits": len(data.get("circuits") or []),
        "bundles": len(data.get("bundles") or []),
        "dependencies": len(deps),
    }


def import_csv_dir(db: Session, directory: Path) -> dict[str, int]:
    """Load optional sites.csv, devices.csv, circuits.csv, bundles.csv, dependencies.csv."""
    payload: dict[str, Any] = {
        "sites": [],
        "devices": [],
        "circuits": [],
        "bundles": [],
        "dependencies": [],
    }

    def rows(name: str) -> list[dict[str, str]]:
        path = directory / name
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    payload["sites"] = rows("sites.csv")
    payload["devices"] = rows("devices.csv")
    circuits = []
    for r in rows("circuits.csv"):
        if r.get("capacity_mbps"):
            r["capacity_mbps"] = int(r["capacity_mbps"])
        circuits.append(r)
    payload["circuits"] = circuits
    bundles = []
    for r in rows("bundles.csv"):
        members = [m.strip() for m in (r.get("members") or "").split("|") if m.strip()]
        r["members"] = members
        bundles.append(r)
    payload["bundles"] = bundles
    deps = []
    for r in rows("dependencies.csv"):
        deps.append(
            {
                "parent": {"type": r["parent_type"], "slug": r["parent_slug"]},
                "child": {"type": r["child_type"], "slug": r["child_slug"]},
            }
        )
    payload["dependencies"] = deps
    return import_payload(db, payload)


def import_any(db: Session, raw: str, filename: str = "topology.yaml") -> dict[str, int]:
    name = filename.lower()
    if name.endswith(".csv"):
        # Single-file CSV is ambiguous; treat as sites if it looks like sites, else error.
        raise ValueError("CSV import expects a directory of files, or use YAML for a single file")
    if name.endswith(".yaml") or name.endswith(".yml") or raw.lstrip().startswith(("sites:", "---")):
        return import_yaml_text(db, raw)
    # Try YAML anyway.
    return import_yaml_text(db, raw)


def csv_from_string(name: str, text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))
