from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ObjectType = Literal["site", "device", "circuit", "bundle"]
AlertStatus = Literal["firing", "resolved"]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    prefix: str
    key: str
    warning: str = "Store this key now. Rootfold will not show it again."


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked: bool


class Ref(BaseModel):
    type: ObjectType
    slug: str


class GenericAlertIn(BaseModel):
    source: str = "generic"
    external_id: str | None = None
    fingerprint: str | None = None
    status: AlertStatus
    severity: str = "warning"
    name: str
    summary: str | None = None
    target: Ref | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class MaintenanceIn(BaseModel):
    object: Ref
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=300)


class MaintenanceOut(BaseModel):
    id: int
    object_type: str
    object_slug: str
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by: str | None = None


class AlertOut(BaseModel):
    id: int
    source: str
    fingerprint: str
    name: str
    summary: str | None = None
    status: str
    severity: str
    object_type: str | None = None
    object_slug: str | None = None
    incident_id: int | None = None
    suppressed: bool
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None = None
    last_ok_at: datetime | None = None


class IncidentOut(BaseModel):
    id: int
    public_ref: str
    status: str
    kind: str
    title: str
    severity: str
    root_type: str | None = None
    root_slug: str | None = None
    parent_incident_id: int | None = None
    blast_radius: dict[str, Any] | None = None
    opened_at: datetime
    resolved_at: datetime | None = None
    sweep_after: datetime | None = None
    alert_count: int = 0
    impact: str | None = None
    urgency: str | None = None
    checks: list[Any] | None = None
    l1_notes: str | None = None
    gate_complete: bool = False
    gate_completed_at: datetime | None = None
    gate_completed_by: str | None = None
    escalated_at: datetime | None = None
    escalated_by: str | None = None
    resolved_by: str | None = None


class TimelineEventOut(BaseModel):
    id: int
    at: datetime
    actor: str
    kind: str
    message: str
    data: dict[str, Any] | None = None


class IncidentDetail(IncidentOut):
    alerts: list[AlertOut] = Field(default_factory=list)
    timeline: list[TimelineEventOut] = Field(default_factory=list)
    children: list[IncidentOut] = Field(default_factory=list)


class GateIn(BaseModel):
    impact: str
    urgency: str
    checks: list[str] = Field(default_factory=list)
    notes: str = ""


class MeOut(BaseModel):
    username: str
    role: str


class BlastRadiusOut(BaseModel):
    root: Ref
    sites: list[str]
    devices: list[str]
    circuits: list[str]
    bundles: list[str]
    customers: list[str]


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    lab_mode: bool
    time: datetime


class ImportResult(BaseModel):
    sites: int
    devices: int
    circuits: int
    bundles: int
    dependencies: int


class IngestResult(BaseModel):
    alerts: list[AlertOut]
    incidents: list[IncidentOut]
    suppressed: int = 0
    message: str = "ok"



class HandoverCloseIn(BaseModel):
    notes: str | None = None


class HandoverAckIn(BaseModel):
    notes: str | None = None


class HandoverOut(BaseModel):
    id: int
    public_ref: str
    status: str
    created_at: datetime
    created_by: str
    outgoing_notes: str | None = None
    snapshot: dict
    acked_at: datetime | None = None
    acked_by: str | None = None
    ack_notes: str | None = None
    pending: bool = False



class ExportIn(BaseModel):
    backend: Literal["jira", "servicenow"]
    dry_run: bool | None = None



class ChecksIn(BaseModel):
    checks: list[str] = Field(default_factory=list)
