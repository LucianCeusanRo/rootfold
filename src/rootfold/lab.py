"""Lab helpers: reset state and inject honest simulated scenarios."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from rootfold.clock import Clock
from rootfold.config import Settings
from rootfold.engine import run_due_sweeps, set_sweep_delay, sweep_delay_seconds
from rootfold.graph import descendants, slug_of
from rootfold.importer import import_yaml_path
from rootfold.models import (
    Alert,
    Bundle,
    BundleMember,
    Circuit,
    Dependency,
    Device,
    Handover,
    Incident,
    IncidentEvent,
    MaintenanceWindow,
    Site,
    TicketExport,
)
from rootfold.service import ingest_source

SCENARIOS = {
    "microwave_fade": {
        "title": "Microwave fade (Onești — Dărmănești)",
        "summary": "The last-mile radio hop goes down; Dărmănești devices alarm as symptoms.",
        "fires": [
            ("circuit", "cir-ons-drm-mw", "Microwave hop down"),
            ("device", "drm-rtr1", "Router unreachable"),
            ("device", "drm-sw1", "Switch unreachable"),
            ("device", "drm-backup", "Backup job failed"),
        ],
    },
    "fiber_los": {
        "title": "Fiber LOS (Bacău PoP — Onești)",
        "summary": "The fiber span to Onești is lost; sites behind it are in the blast radius.",
        "fires": [
            ("circuit", "cir-bcu-ons", "Fiber LOS"),
            ("device", "ons-rtr1", "Router unreachable"),
            ("device", "drm-rtr1", "Router unreachable"),
        ],
    },
    "lacp_member": {
        "title": "LACP member down (core east)",
        "summary": "One member of the core bundle fails; the west member still carries the PoP.",
        "fires": [
            ("circuit", "cir-core-east", "East member down"),
        ],
    },
    "leftover_sweep": {
        "title": "Parent recovers, leftover child remains",
        "summary": "The hop returns and most children get a fresh OK; the backup does not, so a leftover incident is opened.",
        "fires": [],  # handled specially
    },
}


def reset_lab(db: Session, *, reimport: bool = True, example=None) -> dict[str, int]:
    db.query(IncidentEvent).delete()
    db.query(TicketExport).delete()
    db.query(Alert).delete()
    db.query(Incident).delete()
    db.query(Handover).delete()
    db.query(MaintenanceWindow).delete()
    db.flush()
    imported = 0
    if reimport and example is not None:
        stats = import_yaml_path(db, example)
        imported = stats.get("sites", 0)
    db.flush()
    return {"imported_sites": imported}


def _fire(db, clock, settings, typ, slug, name):
    return ingest_source(
        db,
        "generic",
        {
            "status": "firing",
            "name": name,
            "severity": "critical",
            "target": {"type": typ, "slug": slug},
        },
        clock,
        settings,
    )


def _clear(db, clock, settings, typ, slug, name):
    return ingest_source(
        db,
        "generic",
        {
            "status": "resolved",
            "name": name,
            "severity": "critical",
            "target": {"type": typ, "slug": slug},
        },
        clock,
        settings,
    )


def inject(db: Session, name: str, clock: Clock, settings: Settings) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario '{name}'")
    meta = SCENARIOS[name]
    if name != "leftover_sweep":
        ids: list[int] = []
        for typ, slug, title in meta["fires"]:
            _alerts, incidents, _sup, _ = _fire(db, clock, settings, typ, slug, title)
            ids.extend(i.id for i in incidents)
        return {"scenario": name, "title": meta["title"], "incident_ids": sorted(set(ids))}

    # Leftover path: temporarily zero the wait so the demo does not sleep 5 minutes.
    previous = sweep_delay_seconds(db, settings.recovery_sweep_seconds)
    set_sweep_delay(db, 0)
    try:
        _fire(db, clock, settings, "circuit", "cir-ons-drm-mw", "Microwave hop down")
        _fire(db, clock, settings, "device", "drm-rtr1", "Router unreachable")
        _fire(db, clock, settings, "device", "drm-sw1", "Switch unreachable")
        _fire(db, clock, settings, "device", "drm-backup", "Backup job failed")
        _clear(db, clock, settings, "circuit", "cir-ons-drm-mw", "Microwave hop down")
        # After delay=0, sweep_after is "now". Fresh OKs for the router and switch:
        _clear(db, clock, settings, "device", "drm-rtr1", "Router unreachable")
        _clear(db, clock, settings, "device", "drm-sw1", "Switch unreachable")
        leftovers = run_due_sweeps(db, clock, 0)
    finally:
        set_sweep_delay(db, previous)
    return {
        "scenario": name,
        "title": meta["title"],
        "incident_ids": [i.id for i in leftovers],
        "leftover_count": len(leftovers),
    }


def topology_graph(db: Session) -> dict[str, Any]:
    """Nodes and edges for the lab map, with live status from open incidents."""
    down: set[tuple[str, int]] = set()
    for inc in db.query(Incident).filter(Incident.status.in_(("open", "sweep_pending", "escalated"))).all():
        if inc.root_type and inc.root_id is not None:
            down.add((inc.root_type, inc.root_id))
            for typ, oid in descendants(db, (inc.root_type, inc.root_id)):
                down.add((typ, oid))

    def status(typ: str, oid: int) -> str:
        return "down" if (typ, oid) in down else "up"

    nodes = []
    for typ, model in (("site", Site), ("device", Device), ("circuit", Circuit), ("bundle", Bundle)):
        for row in db.query(model).order_by(model.slug).all():
            item = {
                "id": f"{typ}:{row.slug}",
                "type": typ,
                "slug": row.slug,
                "name": row.name,
                "status": status(typ, row.id),
            }
            if typ == "site":
                item["region"] = row.region
            if typ == "device":
                item["role"] = row.role
                item["site"] = row.site.slug if row.site else None
            if typ == "circuit":
                item["media"] = row.media
                a = db.get(Site, row.a_site_id)
                z = db.get(Site, row.z_site_id)
                item["a_site"] = a.slug if a else None
                item["z_site"] = z.slug if z else None
            nodes.append(item)

    edges = []
    for c in db.query(Circuit).all():
        a = db.get(Site, c.a_site_id)
        z = db.get(Site, c.z_site_id)
        if a and z:
            edges.append(
                {
                    "id": f"circuit:{c.slug}",
                    "from": f"site:{a.slug}",
                    "to": f"site:{z.slug}",
                    "kind": "circuit",
                    "media": c.media,
                    "slug": c.slug,
                    "status": status("circuit", c.id),
                }
            )
    for d in db.query(Dependency).all():
        ps, cs = slug_of(db, d.parent_type, d.parent_id), slug_of(db, d.child_type, d.child_id)
        if ps and cs:
            edges.append(
                {
                    "id": f"dep:{d.id}",
                    "from": f"{d.parent_type}:{ps}",
                    "to": f"{d.child_type}:{cs}",
                    "kind": "dependency",
                    "status": "down" if (d.parent_type, d.parent_id) in down else "up",
                }
            )
    for m in db.query(BundleMember).all():
        b = db.get(Bundle, m.bundle_id)
        c = db.get(Circuit, m.circuit_id)
        if b and c:
            edges.append(
                {
                    "id": f"member:{b.slug}:{c.slug}",
                    "from": f"bundle:{b.slug}",
                    "to": f"circuit:{c.slug}",
                    "kind": "member",
                    "status": status("circuit", c.id),
                }
            )
    return {"nodes": nodes, "edges": edges}
