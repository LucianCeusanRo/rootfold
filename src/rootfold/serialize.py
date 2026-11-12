from __future__ import annotations

from sqlalchemy.orm import Session

from rootfold.events import events_for
from rootfold.gate import is_complete
from rootfold.graph import slug_of
from rootfold.models import Alert, Handover, Incident, MaintenanceWindow
from rootfold.schemas import (
    AlertOut,
    HandoverOut,
    IncidentDetail,
    IncidentOut,
    MaintenanceOut,
    TimelineEventOut,
)


def alert_out(db: Session, alert: Alert) -> AlertOut:
    slug = None
    if alert.object_type and alert.object_id is not None:
        slug = slug_of(db, alert.object_type, alert.object_id)
    return AlertOut(
        id=alert.id,
        source=alert.source,
        fingerprint=alert.fingerprint,
        name=alert.name,
        summary=alert.summary,
        status=alert.status,
        severity=alert.severity,
        object_type=alert.object_type,
        object_slug=slug,
        incident_id=alert.incident_id,
        suppressed=alert.suppressed,
        first_seen_at=alert.first_seen_at,
        last_seen_at=alert.last_seen_at,
        resolved_at=alert.resolved_at,
        last_ok_at=alert.last_ok_at,
    )


def incident_out(db: Session, inc: Incident, *, detail: bool = False) -> IncidentOut | IncidentDetail:
    slug = None
    if inc.root_type and inc.root_id is not None:
        slug = slug_of(db, inc.root_type, inc.root_id)
    kwargs = dict(
        id=inc.id,
        public_ref=inc.public_ref,
        status=inc.status,
        kind=inc.kind,
        title=inc.title,
        severity=inc.severity,
        root_type=inc.root_type,
        root_slug=slug,
        parent_incident_id=inc.parent_incident_id,
        blast_radius=inc.blast_radius,
        opened_at=inc.opened_at,
        resolved_at=inc.resolved_at,
        sweep_after=inc.sweep_after,
        alert_count=len(inc.alerts) if inc.alerts is not None else 0,
        impact=inc.impact,
        urgency=inc.urgency,
        checks=inc.checks,
        l1_notes=inc.l1_notes,
        gate_complete=is_complete(inc),
        gate_completed_at=inc.gate_completed_at,
        gate_completed_by=inc.gate_completed_by,
        escalated_at=inc.escalated_at,
        escalated_by=inc.escalated_by,
        resolved_by=inc.resolved_by,
    )
    if detail:
        children = (
            db.query(Incident)
            .filter(Incident.parent_incident_id == inc.id)
            .order_by(Incident.id.asc())
            .all()
        )
        timeline = [
            TimelineEventOut(
                id=e.id, at=e.at, actor=e.actor, kind=e.kind, message=e.message, data=e.data
            )
            for e in events_for(db, inc.id)
        ]
        return IncidentDetail(
            **kwargs,
            alerts=[alert_out(db, a) for a in inc.alerts],
            timeline=timeline,
            children=[incident_out(db, c) for c in children],
        )
    return IncidentOut(**kwargs)


def maintenance_out(db: Session, row: MaintenanceWindow) -> MaintenanceOut:
    return MaintenanceOut(
        id=row.id,
        object_type=row.object_type,
        object_slug=slug_of(db, row.object_type, row.object_id) or "",
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
        created_by=row.created_by,
    )



def handover_out(row: Handover) -> HandoverOut:
    return HandoverOut(
        id=row.id,
        public_ref=row.public_ref,
        status=row.status,
        created_at=row.created_at,
        created_by=row.created_by,
        outgoing_notes=row.outgoing_notes,
        snapshot=row.snapshot or {},
        acked_at=row.acked_at,
        acked_by=row.acked_by,
        ack_notes=row.ack_notes,
        pending=row.status == "pending_ack",
    )
