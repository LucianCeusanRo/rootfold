"""Incident timeline helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from rootfold.models import IncidentEvent


def add_event(
    db: Session,
    incident_id: int,
    *,
    at: datetime,
    kind: str,
    message: str,
    actor: str = "system",
    data: dict[str, Any] | None = None,
) -> IncidentEvent:
    ev = IncidentEvent(
        incident_id=incident_id,
        at=at,
        actor=actor,
        kind=kind,
        message=message,
        data=data,
    )
    db.add(ev)
    db.flush()
    return ev


def events_for(db: Session, incident_id: int) -> list[IncidentEvent]:
    return (
        db.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.at.asc(), IncidentEvent.id.asc())
        .all()
    )
