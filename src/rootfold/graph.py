"""Topology graph helpers: resolve objects, walk deps, blast radius, LACP rules."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from sqlalchemy.orm import Session

from rootfold.models import Bundle, BundleMember, Circuit, Dependency, Device, Site

ObjectKey = tuple[str, int]


def slug_of(db: Session, typ: str, obj_id: int) -> str | None:
    model = {"site": Site, "device": Device, "circuit": Circuit, "bundle": Bundle}.get(typ)
    if model is None:
        return None
    row = db.get(model, obj_id)
    return row.slug if row is not None else None


def resolve(db: Session, typ: str, slug: str) -> tuple[str, int] | None:
    typ = typ.lower()
    model = {"site": Site, "device": Device, "circuit": Circuit, "bundle": Bundle}.get(typ)
    if model is None or not slug:
        return None
    row = db.query(model).filter(model.slug == slug).one_or_none()
    if row is None:
        return None
    return typ, row.id


def resolve_from_labels(db: Session, labels: dict) -> ObjectKey | None:
    """Best-effort mapping from alert labels to a topology object."""
    if not labels:
        return None
    # Explicit type+slug wins.
    for typ in ("circuit", "bundle", "device", "site"):
        if typ in labels and labels[typ]:
            hit = resolve(db, typ, str(labels[typ]))
            if hit:
                return hit
    for typ, keys in (
        ("circuit", ("circuit_slug", "link", "hop")),
        ("bundle", ("bundle_slug", "lag", "lacp")),
        ("device", ("device_slug", "host", "instance", "node")),
        ("site", ("site_slug", "location", "pop")),
    ):
        for key in keys:
            if labels.get(key):
                hit = resolve(db, typ, str(labels[key]))
                if hit:
                    return hit
    # Bare slug match across all object types (unique slugs are required).
    for typ in ("circuit", "bundle", "device", "site"):
        for value in labels.values():
            if isinstance(value, str) and value:
                hit = resolve(db, typ, value)
                if hit:
                    return hit
    return None


def _dep_maps(db: Session) -> tuple[dict[ObjectKey, list[ObjectKey]], dict[ObjectKey, list[ObjectKey]]]:
    parents: dict[ObjectKey, list[ObjectKey]] = defaultdict(list)
    children: dict[ObjectKey, list[ObjectKey]] = defaultdict(list)

    def _edge(p: ObjectKey, c: ObjectKey) -> None:
        if c not in children[p]:
            children[p].append(c)
        if p not in parents[c]:
            parents[c].append(p)

    for d in db.query(Dependency).all():
        _edge((d.parent_type, d.parent_id), (d.child_type, d.child_id))
    # Implicit: a device is a child of its site (if the site uplink dies, the device is a symptom).
    for dev in db.query(Device).all():
        _edge(("site", dev.site_id), ("device", dev.id))
    # Implicit: LACP member circuits are children of their bundle.
    for m in db.query(BundleMember).all():
        _edge(("bundle", m.bundle_id), ("circuit", m.circuit_id))
    return parents, children


def parents_of(db: Session, key: ObjectKey) -> list[ObjectKey]:
    parents, _ = _dep_maps(db)
    return list(parents.get(key, []))


def children_of(db: Session, key: ObjectKey) -> list[ObjectKey]:
    _, children = _dep_maps(db)
    return list(children.get(key, []))


def ancestors(db: Session, key: ObjectKey) -> list[ObjectKey]:
    parents, _ = _dep_maps(db)
    out: list[ObjectKey] = []
    seen: set[ObjectKey] = set()
    q = deque(parents.get(key, []))
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        q.extend(parents.get(n, []))
    return out


def descendants(db: Session, key: ObjectKey) -> list[ObjectKey]:
    _, children = _dep_maps(db)
    out: list[ObjectKey] = []
    seen: set[ObjectKey] = set()
    q = deque(children.get(key, []))
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        q.extend(children.get(n, []))
    return out


def bundle_members(db: Session, bundle_id: int) -> list[ObjectKey]:
    rows = db.query(BundleMember).filter(BundleMember.bundle_id == bundle_id).all()
    return [("circuit", r.circuit_id) for r in rows]


def bundle_for_member(db: Session, circuit_id: int) -> ObjectKey | None:
    row = db.query(BundleMember).filter(BundleMember.circuit_id == circuit_id).one_or_none()
    if row is None:
        return None
    return ("bundle", row.bundle_id)


def blast_radius(db: Session, typ: str, obj_id: int) -> dict:
    root: ObjectKey = (typ, obj_id)
    keys = [root, *descendants(db, root)]
    # Do not auto-add both circuit endpoints: the near-end PoP usually stays up.
    # Far-end impact comes from explicit parent-child dependencies in the topology.
    sites, devices, circuits, bundles, customers = [], [], [], [], []
    seen: set[ObjectKey] = set()
    for typ_, oid in keys:
        if (typ_, oid) in seen:
            continue
        seen.add((typ_, oid))
        if typ_ == "site":
            row = db.get(Site, oid)
            if row:
                sites.append(row.slug)
        elif typ_ == "device":
            row = db.get(Device, oid)
            if row:
                devices.append(row.slug)
        elif typ_ == "circuit":
            row = db.get(Circuit, oid)
            if row:
                circuits.append(row.slug)
                if row.customer:
                    customers.append(row.customer)
        elif typ_ == "bundle":
            row = db.get(Bundle, oid)
            if row:
                bundles.append(row.slug)
    return {
        "root": {"type": typ, "slug": slug_of(db, typ, obj_id)},
        "sites": sorted(set(sites)),
        "devices": sorted(set(devices)),
        "circuits": sorted(set(circuits)),
        "bundles": sorted(set(bundles)),
        "customers": sorted(set(customers)),
    }


def all_objects(db: Session) -> Iterable[ObjectKey]:
    for row in db.query(Site).all():
        yield ("site", row.id)
    for row in db.query(Device).all():
        yield ("device", row.id)
    for row in db.query(Circuit).all():
        yield ("circuit", row.id)
    for row in db.query(Bundle).all():
        yield ("bundle", row.id)
