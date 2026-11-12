"""Shift handover: snapshot open incidents; the incoming shift must acknowledge."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rootfold.engine import OPEN_STATUSES
from rootfold.graph import slug_of
from rootfold.models import Handover, Incident

OPEN_FOR_HANDOVER = OPEN_STATUSES  # open, sweep_pending, escalated


class HandoverError(ValueError):
    pass


def _next_ref(db: Session) -> str:
    last = db.query(Handover).order_by(Handover.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"HO-{n:04d}"


def snapshot_open(db: Session) -> dict:
    rows = (
        db.query(Incident)
        .filter(Incident.status.in_(OPEN_FOR_HANDOVER))
        .order_by(Incident.id.asc())
        .all()
    )
    items = []
    for inc in rows:
        slug = None
        if inc.root_type and inc.root_id is not None:
            slug = slug_of(db, inc.root_type, inc.root_id)
        items.append(
            {
                "id": inc.id,
                "public_ref": inc.public_ref,
                "title": inc.title,
                "status": inc.status,
                "kind": inc.kind,
                "severity": inc.severity,
                "root_slug": slug,
                "gate_complete": bool(inc.gate_completed_at),
            }
        )
    return {"incidents": items, "count": len(items)}


def pending(db: Session) -> Handover | None:
    return (
        db.query(Handover)
        .filter(Handover.status == "pending_ack")
        .order_by(Handover.id.desc())
        .first()
    )


def close_shift(
    db: Session,
    *,
    actor: str,
    now: datetime,
    notes: str | None = None,
) -> Handover:
    existing = pending(db)
    if existing is not None:
        raise HandoverError(
            f"{existing.public_ref} is still waiting for an acknowledgement "
            "before another shift can be closed"
        )
    row = Handover(
        public_ref=_next_ref(db),
        status="pending_ack",
        created_at=now,
        created_by=actor,
        outgoing_notes=(notes or "").strip() or None,
        snapshot=snapshot_open(db),
    )
    db.add(row)
    db.flush()
    return row


def acknowledge(
    db: Session,
    row: Handover,
    *,
    actor: str,
    now: datetime,
    notes: str | None = None,
) -> Handover:
    if row.status == "acked":
        raise HandoverError(f"{row.public_ref} is already acknowledged")
    row.status = "acked"
    row.acked_at = now
    row.acked_by = actor
    row.ack_notes = (notes or "").strip() or None
    db.flush()
    return row
