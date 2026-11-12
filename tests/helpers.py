from __future__ import annotations

from sqlalchemy.orm import Session

from rootfold.clock import Clock
from rootfold.config import Settings
from rootfold.models import Incident
from rootfold.service import ingest_source


def fire(db: Session, clock: Clock, settings: Settings, slug: str, typ: str, name: str | None = None):
    payload = {
        "status": "firing",
        "name": name or f"{slug} down",
        "severity": "critical",
        "target": {"type": typ, "slug": slug},
    }
    return ingest_source(db, "generic", payload, clock, settings)


def clear(db: Session, clock: Clock, settings: Settings, slug: str, typ: str, name: str | None = None):
    payload = {
        "status": "resolved",
        "name": name or f"{slug} down",
        "severity": "critical",
        "target": {"type": typ, "slug": slug},
    }
    return ingest_source(db, "generic", payload, clock, settings)


def open_incidents(db: Session) -> list[Incident]:
    return db.query(Incident).filter(Incident.status.in_(("open", "sweep_pending", "escalated"))).all()


def incidents_by_kind(db: Session, kind: str) -> list[Incident]:
    return db.query(Incident).filter(Incident.kind == kind).all()
