"""Monthly availability: uptime, MTTR, incident count and an SLA-breach flag."""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from rootfold.config import Settings
from rootfold.models import Circuit, Device, Incident, Site


def month_window(year: int, month: int) -> tuple[datetime, datetime]:
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    start = datetime(year, month, 1, tzinfo=UTC)
    last = monthrange(year, month)[1]
    end = datetime(year, month, last, 0, 0, tzinfo=UTC) + timedelta(days=1)
    return start, end


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def overlap_seconds(opened: datetime, closed: datetime, start: datetime, end: datetime) -> float:
    a, b = max(_aware(opened), start), min(_aware(closed), end)
    if b <= a:
        return 0.0
    return (b - a).total_seconds()


def union_seconds(intervals: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> float:
    clipped: list[tuple[datetime, datetime]] = []
    for opened, closed in intervals:
        a, b = max(_aware(opened), start), min(_aware(closed), end)
        if b > a:
            clipped.append((a, b))
    clipped.sort()
    total = 0.0
    cur_a = cur_b = None
    for a, b in clipped:
        if cur_a is None:
            cur_a, cur_b = a, b
        elif a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            total += (cur_b - cur_a).total_seconds()
            cur_a, cur_b = a, b
    if cur_a is not None:
        total += (cur_b - cur_a).total_seconds()
    return total


def _incident_interval(inc: Incident, now: datetime) -> tuple[datetime, datetime]:
    opened = _aware(inc.opened_at)
    closed = _aware(inc.resolved_at) if inc.resolved_at else now
    return opened, closed


def _objects_for(db: Session, inc: Incident) -> set[tuple[str, str, str]]:
    """(scope, slug, name) this incident should count against."""
    found: set[tuple[str, str, str]] = set()
    radius = inc.blast_radius or {}
    for slug in radius.get("sites") or []:
        found.add(("site", slug, slug))
    for slug in radius.get("circuits") or []:
        found.add(("circuit", slug, slug))
    for name in radius.get("customers") or []:
        found.add(("customer", name, name))
    if inc.root_type == "circuit" and inc.root_id is not None:
        circuit = db.get(Circuit, inc.root_id)
        if circuit is not None:
            found.add(("circuit", circuit.slug, circuit.name))
            if circuit.customer:
                found.add(("customer", circuit.customer, circuit.customer))
    elif inc.root_type == "site" and inc.root_id is not None:
        site = db.get(Site, inc.root_id)
        if site is not None:
            found.add(("site", site.slug, site.name))
    elif inc.root_type == "device" and inc.root_id is not None:
        device = db.get(Device, inc.root_id)
        if device is not None and device.site is not None:
            found.add(("site", device.site.slug, device.site.name))
    return found


def _row(
    scope: str,
    slug: str,
    name: str,
    intervals: list[tuple[datetime, datetime]],
    incidents: list[Incident],
    start: datetime,
    end: datetime,
    now: datetime,
    sla: float,
) -> dict[str, Any]:
    period = (end - start).total_seconds()
    down = union_seconds(intervals, start, end)
    uptime = 100.0 * (1.0 - (down / period if period else 0.0))
    # Guard floating-point crumbs above 100.
    uptime = min(100.0, max(0.0, uptime))
    repaired = [i for i in incidents if i.resolved_at is not None]
    if repaired:
        mttr = sum(
            (_aware(i.resolved_at) - _aware(i.opened_at)).total_seconds() for i in repaired
        ) / len(repaired)
    else:
        mttr = None
    return {
        "scope": scope,
        "slug": slug,
        "name": name,
        "incident_count": len(incidents),
        "downtime_seconds": int(round(down)),
        "uptime_percent": round(uptime, 4),
        "mttr_seconds": int(round(mttr)) if mttr is not None else None,
        "sla_percent": sla,
        "sla_breach": bool(uptime + 1e-9 < sla),
    }


def build_availability(
    db: Session,
    *,
    year: int,
    month: int,
    now: datetime,
    settings: Settings,
) -> dict[str, Any]:
    start, end = month_window(year, month)
    sla = float(settings.sla_percent)
    incidents = db.query(Incident).order_by(Incident.id.asc()).all()
    overlapping = []
    for inc in incidents:
        opened, closed = _incident_interval(inc, now)
        if overlap_seconds(opened, closed, start, end) > 0 or (
            start <= _aware(inc.opened_at) < end
        ):
            overlapping.append(inc)

    buckets: dict[tuple[str, str], dict[str, Any]] = {}

    def bucket(scope: str, slug: str, name: str) -> dict[str, Any]:
        key = (scope, slug)
        if key not in buckets:
            buckets[key] = {"scope": scope, "slug": slug, "name": name, "intervals": [], "incidents": []}
        elif name and buckets[key]["name"] == buckets[key]["slug"] and name != slug:
            buckets[key]["name"] = name
        return buckets[key]

    for site in db.query(Site).order_by(Site.slug).all():
        bucket("site", site.slug, site.name)
    for circuit in db.query(Circuit).order_by(Circuit.slug).all():
        bucket("circuit", circuit.slug, circuit.name)
        if circuit.customer:
            bucket("customer", circuit.customer, circuit.customer)

    for inc in overlapping:
        opened, closed = _incident_interval(inc, now)
        for scope, slug, name in _objects_for(db, inc):
            item = bucket(scope, slug, name)
            if inc not in item["incidents"]:
                item["intervals"].append((opened, closed))
                item["incidents"].append(inc)

    rows = [
        _row(
            item["scope"],
            item["slug"],
            item["name"],
            item["intervals"],
            item["incidents"],
            start,
            end,
            now,
            sla,
        )
        for _, item in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]
    breaches = sum(1 for r in rows if r["sla_breach"])
    return {
        "year": year,
        "month": month,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "sla_percent": sla,
        "object_count": len(rows),
        "breach_count": breaches,
        "incident_count": len(overlapping),
        "rows": rows,
    }


def to_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    fields = [
        "scope",
        "slug",
        "name",
        "incident_count",
        "downtime_seconds",
        "uptime_percent",
        "mttr_seconds",
        "sla_percent",
        "sla_breach",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in report["rows"]:
        writer.writerow({k: row[k] for k in fields})
    return buf.getvalue()
