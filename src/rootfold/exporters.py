"""Export an incident to Jira (REST v3) or ServiceNow (incident table API).

When a backend is not configured, export stays in dry-run and only returns the
payload the operator would have sent. Tests mock HTTP; nothing is sent unless
URL and credentials are set and dry_run is false.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from rootfold.config import Settings
from rootfold.events import add_event
from rootfold.graph import slug_of
from rootfold.models import Incident, TicketExport

BACKENDS = ("jira", "servicenow")


class ExportError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def jira_configured(settings: Settings) -> bool:
    return bool(settings.jira_url and settings.jira_user and settings.jira_token)


def snow_configured(settings: Settings) -> bool:
    return bool(settings.snow_url and settings.snow_user and settings.snow_password)


def configured(settings: Settings, backend: str) -> bool:
    if backend == "jira":
        return jira_configured(settings)
    if backend == "servicenow":
        return snow_configured(settings)
    return False


def _impact_urgency(inc: Incident) -> tuple[str, str]:
    impact = inc.impact or "degraded"
    urgency = inc.urgency or "medium"
    return impact, urgency


def _snow_codes(impact: str, urgency: str) -> tuple[str, str]:
    """ServiceNow uses 1 (high) – 3 (low)."""
    impact_map = {"site-down": "1", "customer-impact": "1", "degraded": "2", "no-customer-impact": "3"}
    urgency_map = {"high": "1", "medium": "2", "low": "3"}
    return impact_map.get(impact, "2"), urgency_map.get(urgency, "2")


def _summary(inc: Incident) -> str:
    return f"{inc.public_ref}: {inc.title}"


def _plain_body(db: Session, inc: Incident) -> str:
    root = ""
    if inc.root_type and inc.root_id is not None:
        root = f"{inc.root_type}:{slug_of(db, inc.root_type, inc.root_id)}"
    radius = inc.blast_radius or {}
    lines = [
        f"Rootfold incident {inc.public_ref}",
        f"Title: {inc.title}",
        f"Status: {inc.status}  Severity: {inc.severity}  Kind: {inc.kind}",
        f"Root: {root or 'unmapped'}",
        f"Opened: {inc.opened_at.isoformat() if inc.opened_at else '—'}",
        f"Impact: {inc.impact or '—'}  Urgency: {inc.urgency or '—'}",
        f"Checks: {', '.join(inc.checks or []) or '—'}",
        f"L1 notes: {inc.l1_notes or inc.notes or '—'}",
        "Blast radius:",
        f"  sites: {', '.join(radius.get('sites') or []) or '—'}",
        f"  circuits: {', '.join(radius.get('circuits') or []) or '—'}",
        f"  customers: {', '.join(radius.get('customers') or []) or '—'}",
        "Alerts:",
    ]
    for alert in inc.alerts or []:
        lines.append(f"  - {alert.name} [{alert.status}] {alert.object_type or ''}")
    lines.append("")
    lines.append(
        "Honest disclaimer: if this came from the lab, the inventory is simulated, not a production network."
    )
    return "\n".join(lines)


def _adf(text: str) -> dict[str, Any]:
    """Atlassian Document Format used by Jira Cloud REST v3 descriptions."""
    paragraphs = []
    for block in text.split("\n"):
        if block == "":
            paragraphs.append({"type": "paragraph", "content": []})
        else:
            paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": block}]})
    if not paragraphs:
        paragraphs = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": paragraphs}


def build_jira_payload(db: Session, inc: Incident, settings: Settings) -> dict[str, Any]:
    impact, urgency = _impact_urgency(inc)
    priority = {"high": "High", "medium": "Medium", "low": "Low"}.get(urgency, "Medium")
    return {
        "fields": {
            "project": {"key": settings.jira_project},
            "issuetype": {"name": settings.jira_issue_type},
            "summary": _summary(inc),
            "description": _adf(_plain_body(db, inc)),
            "priority": {"name": priority},
            "labels": ["rootfold", inc.kind, inc.severity, impact],
        }
    }


def build_snow_payload(db: Session, inc: Incident, settings: Settings) -> dict[str, Any]:
    impact, urgency = _impact_urgency(inc)
    impact_code, urgency_code = _snow_codes(impact, urgency)
    return {
        "short_description": _summary(inc),
        "description": _plain_body(db, inc),
        "impact": impact_code,
        "urgency": urgency_code,
        "category": "Network",
        "subcategory": inc.root_type or "outage",
        "caller_id": settings.snow_user or "rootfold",
    }


def build_payload(db: Session, inc: Incident, settings: Settings, backend: str) -> dict[str, Any]:
    if backend == "jira":
        return build_jira_payload(db, inc, settings)
    if backend == "servicenow":
        return build_snow_payload(db, inc, settings)
    raise ExportError(f"Unknown export backend '{backend}'")


def _jira_headers(settings: Settings) -> dict[str, str]:
    raw = f"{settings.jira_user}:{settings.jira_token}".encode()
    token = base64.b64encode(raw).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _snow_headers(settings: Settings) -> dict[str, str]:
    raw = f"{settings.snow_user}:{settings.snow_password}".encode()
    token = base64.b64encode(raw).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _send(
    backend: str,
    settings: Settings,
    payload: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if backend == "jira":
        url = settings.jira_url.rstrip("/") + "/rest/api/3/issue"
        headers = _jira_headers(settings)
    else:
        url = settings.snow_url.rstrip("/") + "/api/now/table/incident"
        headers = _snow_headers(settings)
    own = client is None
    http = client or httpx.Client(timeout=20.0)
    try:
        response = http.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise ExportError(
                f"{backend} returned HTTP {response.status_code}: {response.text[:400]}",
                status_code=response.status_code,
            )
        body = response.json() if response.content else {}
        if backend == "jira":
            key = body.get("key")
            self_url = body.get("self") or f"{settings.jira_url.rstrip('/')}/browse/{key}"
            return {"external_key": key, "url": self_url, "response": body}
        result = body.get("result") or body
        number = result.get("number") or result.get("sys_id")
        sys_id = result.get("sys_id")
        rec_url = f"{settings.snow_url.rstrip('/')}/nav_to.do?uri=incident.do?sys_id={sys_id}" if sys_id else None
        return {"external_key": number, "url": rec_url, "response": body}
    except httpx.HTTPError as exc:
        raise ExportError(f"{backend} request failed: {exc}") from exc
    finally:
        if own:
            http.close()


def export_incident(
    db: Session,
    inc: Incident,
    settings: Settings,
    backend: str,
    *,
    actor: str,
    now: datetime,
    dry_run: bool | None = None,
    client: httpx.Client | None = None,
) -> TicketExport:
    if backend not in BACKENDS:
        raise ExportError(f"Unknown export backend '{backend}'")
    ready = configured(settings, backend)
    if dry_run is None:
        dry_run = not ready
    if not dry_run and not ready:
        raise ExportError(
            f"{backend} is not configured; export is only available as a dry-run preview"
        )
    payload = build_payload(db, inc, settings, backend)
    row = TicketExport(
        incident_id=inc.id,
        backend=backend,
        dry_run=bool(dry_run),
        status="preview" if dry_run else "sent",
        payload=payload,
        created_at=now,
        created_by=actor,
    )
    if not dry_run:
        try:
            sent = _send(backend, settings, payload, client=client)
        except ExportError:
            row.status = "error"
            row.dry_run = False
            db.add(row)
            db.flush()
            raise
        row.external_key = sent.get("external_key")
        row.url = sent.get("url")
        row.response = sent.get("response")
        add_event(
            db,
            inc.id,
            at=now,
            actor=actor,
            kind="export",
            message=f"Exported to {backend} as {row.external_key}",
            data={"backend": backend, "external_key": row.external_key, "url": row.url},
        )
    db.add(row)
    db.flush()
    return row


def export_out(row: TicketExport) -> dict[str, Any]:
    return {
        "id": row.id,
        "incident_id": row.incident_id,
        "backend": row.backend,
        "dry_run": row.dry_run,
        "status": row.status,
        "external_key": row.external_key,
        "url": row.url,
        "payload": row.payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }
