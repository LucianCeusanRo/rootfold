"""L1 quality gate: an operator cannot escalate or resolve until the ticket is complete."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rootfold.events import add_event
from rootfold.models import Incident

IMPACTS = ("site-down", "degraded", "customer-impact", "no-customer-impact")
URGENCIES = ("high", "medium", "low")
MIN_NOTES = 10

# Operator-initiated closes. Sweep auto-resolve is not an L1 action and skips the gate.
OPERATOR_ACTIONS = ("escalate", "resolve")


class GateError(ValueError):
    def __init__(self, missing: list[str], message: str | None = None) -> None:
        self.missing = missing
        super().__init__(message or "; ".join(missing))


def missing_fields(inc: Incident) -> list[str]:
    missing: list[str] = []
    if inc.impact not in IMPACTS:
        missing.append("impact")
    if inc.urgency not in URGENCIES:
        missing.append("urgency")
    checks = inc.checks or []
    if not isinstance(checks, list) or not any(str(c).strip() for c in checks):
        missing.append("checks")
    if not inc.l1_notes or len(inc.l1_notes.strip()) < MIN_NOTES:
        missing.append("notes")
    return missing


def is_complete(inc: Incident) -> bool:
    return not missing_fields(inc)


def apply_gate(
    db: Session,
    inc: Incident,
    *,
    impact: str,
    urgency: str,
    checks: list[str],
    notes: str,
    actor: str,
    now: datetime,
) -> Incident:
    inc.impact = impact
    inc.urgency = urgency
    inc.checks = [str(c).strip() for c in checks if str(c).strip()]
    inc.l1_notes = notes.strip()
    missing = missing_fields(inc)
    if missing:
        # Persist the partial draft so the operator does not retype, but do not mark complete.
        inc.gate_completed_at = None
        inc.gate_completed_by = None
        db.flush()
        raise GateError(missing, f"Quality gate incomplete: {', '.join(missing)}")
    inc.gate_completed_at = now
    inc.gate_completed_by = actor
    add_event(
        db,
        inc.id,
        at=now,
        actor=actor,
        kind="gate",
        message=f"L1 gate completed by {actor} (impact={inc.impact}, urgency={inc.urgency})",
        data={"impact": inc.impact, "urgency": inc.urgency, "checks": inc.checks},
    )
    db.flush()
    return inc


def require_complete(inc: Incident, action: str) -> None:
    if inc.status == "resolved":
        raise GateError([], f"Incident {inc.public_ref} is already resolved")
    if action == "escalate" and inc.status == "escalated":
        raise GateError([], f"Incident {inc.public_ref} is already escalated")
    missing = missing_fields(inc)
    if missing:
        raise GateError(
            missing,
            f"Cannot {action} {inc.public_ref} until the L1 quality gate is complete "
            f"(missing: {', '.join(missing)})",
        )


def escalate(db: Session, inc: Incident, *, actor: str, now: datetime) -> Incident:
    require_complete(inc, "escalate")
    inc.status = "escalated"
    inc.escalated_at = now
    inc.escalated_by = actor
    add_event(
        db,
        inc.id,
        at=now,
        actor=actor,
        kind="escalated",
        message=f"Escalated by {actor}",
    )
    db.flush()
    return inc


def operator_resolve(db: Session, inc: Incident, *, actor: str, now: datetime) -> Incident:
    require_complete(inc, "resolve")
    inc.status = "resolved"
    inc.resolved_at = now
    inc.resolved_by = actor
    add_event(
        db,
        inc.id,
        at=now,
        actor=actor,
        kind="resolved",
        message=f"Resolved by {actor}",
    )
    db.flush()
    return inc
