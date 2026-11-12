"""Correlation, blast radius, maintenance suppression, and the recovery sweep."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from rootfold import graph
from rootfold.clock import Clock
from rootfold.events import add_event
from rootfold.graph import ObjectKey
from rootfold.models import Alert, Incident, MaintenanceWindow, Setting

OPEN_STATUSES = ("open", "sweep_pending", "escalated")


def sweep_delay_seconds(db: Session, default: int) -> int:
    row = db.get(Setting, "recovery_sweep_seconds")
    if row is None:
        return default
    try:
        return int(row.value)
    except ValueError:
        return default


def set_sweep_delay(db: Session, seconds: int) -> None:
    row = db.get(Setting, "recovery_sweep_seconds")
    if row is None:
        db.add(Setting(key="recovery_sweep_seconds", value=str(seconds)))
    else:
        row.value = str(seconds)


def _next_ref(db: Session) -> str:
    last = db.query(Incident).order_by(Incident.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"INC-{n:04d}"


def _firing_keys(db: Session) -> set[ObjectKey]:
    rows = (
        db.query(Alert)
        .filter(Alert.status == "firing", Alert.suppressed.is_(False), Alert.object_type.isnot(None))
        .all()
    )
    return {(a.object_type, a.object_id) for a in rows if a.object_id is not None}


def under_maintenance(db: Session, key: ObjectKey, now: datetime) -> bool:
    """True if this object or any ancestor is in an active maintenance window."""
    keys = [key, *graph.ancestors(db, key)]
    for typ, oid in keys:
        hit = (
            db.query(MaintenanceWindow)
            .filter(
                MaintenanceWindow.object_type == typ,
                MaintenanceWindow.object_id == oid,
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at >= now,
            )
            .first()
        )
        if hit is not None:
            return True
    return False


def _all_bundle_members_firing(db: Session, circuit_id: int, firing: set[ObjectKey]) -> ObjectKey | None:
    bundle = graph.bundle_for_member(db, circuit_id)
    if bundle is None:
        return None
    members = graph.bundle_members(db, bundle[1])
    if members and all(m in firing or m == ("circuit", circuit_id) for m in members):
        return bundle
    return None


def highest_firing_root(db: Session, key: ObjectKey, firing: set[ObjectKey]) -> ObjectKey:
    """Walk up the dependency tree and pick the topmost currently firing ancestor (or self).

    If every member of an LACP bundle is firing, the bundle itself becomes the root
    even when the bundle has no direct alert of its own.
    """
    start = key
    if key[0] == "circuit":
        bundle = _all_bundle_members_firing(db, key[1], firing)
        if bundle is not None:
            start = bundle
    root = start
    for anc in graph.ancestors(db, start):
        if anc in firing:
            root = anc
    if root in firing:
        return root
    if start != key:
        return start
    return key


def _open_incidents_for(db: Session, keys: list[ObjectKey]) -> list[Incident]:
    if not keys:
        return []
    inc = db.query(Incident).filter(Incident.status.in_(OPEN_STATUSES)).all()
    wanted = set(keys)
    return [i for i in inc if i.root_type and i.root_id is not None and (i.root_type, i.root_id) in wanted]


def _attach(alert: Alert, incident: Incident) -> None:
    alert.incident_id = incident.id
    incident.severity = _worse(incident.severity, alert.severity)


def _worse(a: str, b: str) -> str:
    rank = {"info": 0, "warning": 1, "minor": 1, "major": 2, "error": 2, "critical": 3, "disaster": 4, "high": 2}
    return b if rank.get(b.lower(), 1) > rank.get(a.lower(), 1) else a


def _title_for(db: Session, key: ObjectKey, alert: Alert) -> str:
    slug = graph.slug_of(db, key[0], key[1]) or "unknown"
    return f"{key[0].capitalize()} {slug} down — {alert.name}"


def _refresh_blast(db: Session, incident: Incident) -> None:
    if incident.root_type and incident.root_id is not None:
        incident.blast_radius = graph.blast_radius(db, incident.root_type, incident.root_id)


def merge_incidents(db: Session, into: Incident, others: list[Incident], now: datetime) -> None:
    for inc in others:
        if inc.id == into.id:
            continue
        for alert in list(inc.alerts):
            alert.incident_id = into.id
        inc.status = "resolved"
        inc.resolved_at = now
        inc.notes = (inc.notes or "") + f"\nMerged into {into.public_ref} as a symptom."
        inc.parent_incident_id = into.id
    _refresh_blast(db, into)


def ingest_normalized(
    db: Session,
    *,
    source: str,
    fingerprint: str,
    name: str,
    status: str,
    severity: str,
    summary: str | None,
    object_key: ObjectKey | None,
    labels: dict,
    raw: dict,
    external_id: str | None,
    clock: Clock,
    default_sweep_seconds: int,
) -> tuple[Alert, Incident | None, str]:
    """Apply one canonical alert. Returns (alert, incident_or_none, action)."""
    now = clock.now()
    alert = (
        db.query(Alert)
        .filter(Alert.source == source, Alert.fingerprint == fingerprint)
        .one_or_none()
    )
    if alert is None:
        alert = Alert(
            source=source,
            fingerprint=fingerprint,
            name=name,
            first_seen_at=now,
            last_seen_at=now,
            status=status,
            severity=severity,
        )
        db.add(alert)
        db.flush()
    alert.name = name
    alert.summary = summary
    alert.severity = severity
    alert.labels = labels
    alert.raw = raw
    alert.external_id = external_id
    alert.last_seen_at = now
    if object_key:
        alert.object_type, alert.object_id = object_key

    if object_key and under_maintenance(db, object_key, now):
        alert.suppressed = True
        if status == "resolved":
            alert.status = "resolved"
            alert.resolved_at = now
        else:
            alert.status = "firing"
        db.flush()
        return alert, None, "suppressed"

    alert.suppressed = False

    if status == "resolved":
        return _on_resolve(db, alert, clock, default_sweep_seconds)

    # firing
    alert.status = "firing"
    alert.resolved_at = None
    db.flush()
    if not object_key:
        # Unmapped alert: stand-alone incident so nothing is silently dropped.
        inc = _ensure_standalone(db, alert, now)
        return alert, inc, "unmapped"

    firing = _firing_keys(db)
    root = highest_firing_root(db, object_key, firing)
    return _ensure_correlated(db, alert, root, now)


def _ensure_standalone(db: Session, alert: Alert, now: datetime) -> Incident:
    if alert.incident_id:
        inc = db.get(Incident, alert.incident_id)
        if inc and inc.status in OPEN_STATUSES:
            return inc
    inc = Incident(
        public_ref=_next_ref(db),
        status="open",
        kind="outage",
        title=alert.name,
        severity=alert.severity,
        opened_at=now,
    )
    db.add(inc)
    db.flush()
    alert.incident_id = inc.id
    inc.root_alert_id = alert.id
    return inc


def _ensure_correlated(
    db: Session, alert: Alert, root: ObjectKey, now: datetime
) -> tuple[Alert, Incident, str]:
    # Existing open incident whose root is this root, or an ancestor, or a descendant
    # (we'll promote / merge).
    family = [root, *graph.ancestors(db, root), *graph.descendants(db, root)]
    existing = _open_incidents_for(db, family)
    # Prefer an incident already rooted at `root`.
    chosen = next((i for i in existing if (i.root_type, i.root_id) == root), None)
    if chosen is None and existing:
        # If a descendant already has an incident, promote it to this higher root.
        chosen = existing[0]
        chosen.root_type, chosen.root_id = root
        chosen.root_alert_id = alert.id
        chosen.title = _title_for(db, root, alert)
        others = [i for i in existing if i.id != chosen.id]
        merge_incidents(db, chosen, others, now)
        action = "promoted"
    elif chosen is not None:
        others = [i for i in existing if i.id != chosen.id]
        if others:
            merge_incidents(db, chosen, others, now)
        action = "folded"
    else:
        chosen = Incident(
            public_ref=_next_ref(db),
            status="open",
            kind="outage",
            title=_title_for(db, root, alert),
            severity=alert.severity,
            root_type=root[0],
            root_id=root[1],
            root_alert_id=alert.id,
            opened_at=now,
        )
        db.add(chosen)
        db.flush()
        action = "opened"
    # If this alert is the root object's own alert, mark it as the root alert.
    if (alert.object_type, alert.object_id) == root:
        chosen.root_alert_id = alert.id
        chosen.title = _title_for(db, root, alert)
    _attach(alert, chosen)
    _refresh_blast(db, chosen)
    db.flush()
    if action == "opened":
        add_event(
            db,
            chosen.id,
            at=now,
            kind="opened",
            message=f"Incident opened from {alert.name}",
            data={"alert_id": alert.id, "root": f"{root[0]}:{root[1]}"},
        )
    else:
        add_event(
            db,
            chosen.id,
            at=now,
            kind="alert-folded",
            message=f"Alert folded: {alert.name}",
            data={"alert_id": alert.id, "action": action},
        )
    return alert, chosen, action


def _on_resolve(
    db: Session, alert: Alert, clock: Clock, default_sweep_seconds: int
) -> tuple[Alert, Incident | None, str]:
    now = clock.now()
    was_firing = alert.status == "firing"
    alert.status = "resolved"
    alert.resolved_at = now
    db.flush()

    if not alert.incident_id:
        alert.last_ok_at = now
        return alert, None, "resolved"

    inc = db.get(Incident, alert.incident_id)
    if inc is None or inc.status == "resolved":
        alert.last_ok_at = now
        return alert, inc, "resolved"

    is_root = inc.root_alert_id == alert.id or (
        inc.root_type and alert.object_type == inc.root_type and alert.object_id == inc.root_id
    )

    if not is_root:
        # Child clears that arrive *with* the parent (or before the sweep window
        # ends) are stale — they do not count as a fresh OK. We still record
        # resolved_at, but last_ok_at stays empty until after sweep_after.
        if inc.status == "sweep_pending" and inc.sweep_after and now >= inc.sweep_after:
            alert.last_ok_at = now
        elif inc.status != "sweep_pending":
            # Parent still down: a child OK while the parent is down is not a
            # post-recovery success either (the child may just be unreachable).
            pass
        return alert, inc, "child-resolved"

    # Root alert cleared: start the recovery sweep window. Do not resolve yet.
    delay = sweep_delay_seconds(db, default_sweep_seconds)
    inc.status = "sweep_pending"
    inc.sweep_after = now + timedelta(seconds=delay)
    inc.resolved_at = None
    # The root's own clear is the start of the wait, not a child OK.
    db.flush()
    add_event(
        db,
        inc.id,
        at=now,
        kind="sweep-scheduled",
        message=f"Parent cleared; recovery sweep scheduled in {delay}s",
        data={"sweep_after": inc.sweep_after.isoformat() if inc.sweep_after else None},
    )
    action = "sweep-scheduled"
    # If delay is 0, the caller may run the sweep immediately after any fresh OKs.
    if delay == 0:
        # Still require the caller to run the sweep so tests can send leftover
        # or fresh OKs first when they want to. We only auto-run when delay==0
        # *and* this was a late resolve with no children? Safer to never auto-run
        # here; expose run_due_sweeps explicitly (and a background tick in the app).
        pass
    return alert, inc, action if was_firing or True else "resolved"


def run_due_sweeps(db: Session, clock: Clock, default_sweep_seconds: int) -> list[Incident]:
    """Close parent incidents whose wait is over; open leftovers for children without a fresh OK.

    Fresh OK = last_ok_at >= sweep_after (a success *after* the stabilize window).
    A resolve that arrived at parent-recovery time does not count — that is the
    Sept 2026 r/networking failure mode (auto-closed child tickets hiding a
    leftover backup failure).
    """
    now = clock.now()
    due = (
        db.query(Incident)
        .filter(Incident.status == "sweep_pending", Incident.sweep_after.isnot(None), Incident.sweep_after <= now)
        .all()
    )
    created: list[Incident] = []
    for inc in due:
        leftovers = []
        for alert in list(inc.alerts):
            is_root = inc.root_alert_id == alert.id or (
                inc.root_type
                and alert.object_type == inc.root_type
                and alert.object_id == inc.root_id
            )
            if is_root:
                continue
            fresh = alert.last_ok_at is not None and inc.sweep_after is not None and alert.last_ok_at >= inc.sweep_after
            still_down = alert.status == "firing"
            if still_down or not fresh:
                leftovers.append(alert)
        inc.status = "resolved"
        inc.resolved_at = now
        inc.resolved_by = "sweep"
        _refresh_blast(db, inc)
        add_event(
            db,
            inc.id,
            at=now,
            kind="resolved",
            message="Parent closed by recovery sweep",
            actor="sweep",
        )
        for alert in leftovers:
            # Detach into a new incident so the leftover is not buried with the parent.
            child = Incident(
                public_ref=_next_ref(db),
                status="open",
                kind="leftover",
                title=f"Leftover after {inc.public_ref}: {alert.name}",
                severity=alert.severity,
                root_type=alert.object_type,
                root_id=alert.object_id,
                root_alert_id=alert.id,
                parent_incident_id=inc.id,
                opened_at=now,
                notes=(
                    f"Opened by the recovery sweep of {inc.public_ref}. "
                    "The parent recovered, but this child had no fresh OK after the wait window."
                ),
            )
            db.add(child)
            db.flush()
            if child.root_type and child.root_id is not None:
                child.blast_radius = graph.blast_radius(db, child.root_type, child.root_id)
            alert.incident_id = child.id
            created.append(child)
            add_event(
                db,
                child.id,
                at=now,
                kind="opened",
                message=f"Leftover opened after sweep of {inc.public_ref}",
                actor="sweep",
                data={"parent_incident_id": inc.id, "alert_id": alert.id},
            )
            add_event(
                db,
                inc.id,
                at=now,
                kind="leftover",
                message=f"Leftover {child.public_ref} opened for {alert.name}",
                actor="sweep",
                data={"leftover_id": child.id},
            )
        db.flush()
    return created


def record_fresh_ok_if_due(db: Session, alert: Alert, now: datetime) -> None:
    """Mark a child OK as fresh only when the parent incident's wait has elapsed."""
    if not alert.incident_id:
        alert.last_ok_at = now
        return
    inc = db.get(Incident, alert.incident_id)
    if inc is None:
        alert.last_ok_at = now
        return
    if inc.status == "sweep_pending" and inc.sweep_after and now >= inc.sweep_after:
        alert.last_ok_at = now
