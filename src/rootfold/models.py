from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from rootfold.db import Base


class TZDateTime(TypeDecorator):
    """Store UTC, always return timezone-aware values (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value



class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    devices: Mapped[list[Device]] = relationship(back_populates="site")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))  # router, switch, radio, server, firewall, mux
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    management_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    site: Mapped[Site] = relationship(back_populates="devices")


class Circuit(Base):
    """A hop or leased circuit: fiber span, microwave radio hop, etc."""

    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    media: Mapped[str] = mapped_column(String(32))  # fiber, microwave, copper, lte
    a_site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    z_site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    a_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    z_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    capacity_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vendor_circuit_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Bundle(Base):
    """LACP (or similar) bundle of member circuits on a device."""

    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))


class BundleMember(Base):
    __tablename__ = "bundle_members"
    __table_args__ = (UniqueConstraint("bundle_id", "circuit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), index=True)
    circuit_id: Mapped[int] = mapped_column(ForeignKey("circuits.id"), index=True)


class Dependency(Base):
    """Directed edge: if the parent fails, the child is likely a symptom."""

    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint("parent_type", "parent_id", "child_type", "child_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_type: Mapped[str] = mapped_column(String(20))  # site, device, circuit, bundle
    parent_id: Mapped[int] = mapped_column(Integer, index=True)
    child_type: Mapped[str] = mapped_column(String(20))
    child_id: Mapped[int] = mapped_column(Integer, index=True)


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="operator")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[int] = mapped_column(Integer, index=True)
    starts_at: Mapped[datetime] = mapped_column(TZDateTime())
    ends_at: Mapped[datetime] = mapped_column(TZDateTime())
    reason: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_ref: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    # open | sweep_pending | resolved
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    root_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    root_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="outage")
    # outage | leftover
    blast_radius: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(TZDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    sweep_after: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # L1 quality gate — required before an operator escalates or resolves.
    impact: Mapped[str | None] = mapped_column(String(40), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checks: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    l1_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    gate_completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    gate_completed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    escalated_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    alerts: Mapped[list[Alert]] = relationship(back_populates="incident")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("source", "fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # firing | resolved
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    object_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Last OK that counts for a recovery sweep (must be after the parent wait window).
    last_ok_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    incident: Mapped[Incident | None] = relationship(back_populates="alerts")


class Setting(Base):
    """Runtime key/value so sweep delay can be changed without a restart."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class IncidentEvent(Base):
    """Timeline entry for an incident (alerts, gate, escalate, sweep, notes)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    at: Mapped[datetime] = mapped_column(TZDateTime())
    actor: Mapped[str] = mapped_column(String(80), default="system")
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(400))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Handover(Base):
    """End-of-shift report auto-built from open incidents; incoming shift must ack."""

    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_ref: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # pending_ack | acked
    created_at: Mapped[datetime] = mapped_column(TZDateTime())
    created_by: Mapped[str] = mapped_column(String(80))
    outgoing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    acked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    acked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ack_notes: Mapped[str | None] = mapped_column(Text, nullable=True)



class TicketExport(Base):
    """A Jira or ServiceNow ticket created from an incident (or a dry-run preview)."""

    __tablename__ = "ticket_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    backend: Mapped[str] = mapped_column(String(20))  # jira | servicenow
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="preview")  # preview | sent | error
    external_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime())
    created_by: Mapped[str] = mapped_column(String(80))
