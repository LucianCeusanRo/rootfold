from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.orm import Session

from rootfold import engine as eng
from rootfold.clock import Clock
from rootfold.config import Settings
from rootfold.graph import resolve, resolve_from_labels
from rootfold.ingest import iter_alertmanager, iter_generic, iter_zabbix
from rootfold.models import Alert, Incident

PARSERS: dict[str, Callable[[Any], Iterable[dict]]] = {
    "alertmanager": iter_alertmanager,
    "zabbix": iter_zabbix,
    "generic": iter_generic,
}


def ingest_source(
    db: Session,
    source: str,
    payload: Any,
    clock: Clock,
    settings: Settings,
) -> tuple[list[Alert], list[Incident], int, list[str]]:
    parser = PARSERS.get(source)
    if parser is None:
        raise ValueError(f"Unknown ingest source: {source}")
    alerts: list[Alert] = []
    incidents: dict[int, Incident] = {}
    suppressed = 0
    actions: list[str] = []
    for item in parser(payload):
        key = resolve_from_labels(db, item.get("labels") or {})
        alert, inc, action = eng.ingest_normalized(
            db,
            source=item["source"],
            fingerprint=item["fingerprint"],
            name=item["name"],
            status=item["status"],
            severity=str(item.get("severity") or "warning"),
            summary=item.get("summary"),
            object_key=key,
            labels=item.get("labels") or {},
            raw=item.get("raw") or item,
            external_id=item.get("external_id"),
            clock=clock,
            default_sweep_seconds=settings.recovery_sweep_seconds,
        )
        alerts.append(alert)
        actions.append(action)
        if action == "suppressed":
            suppressed += 1
        if inc is not None:
            incidents[inc.id] = inc
    return alerts, list(incidents.values()), suppressed, actions


def resolve_ref(db: Session, typ: str, slug: str):
    hit = resolve(db, typ, slug)
    if hit is None:
        raise KeyError(f"Unknown {typ} '{slug}'")
    return hit
