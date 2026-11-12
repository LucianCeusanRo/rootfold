"""Normalize Alertmanager, Zabbix, and generic payloads into canonical alerts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from rootfold.schemas import GenericAlertIn


def _fp(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def iter_alertmanager(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    alerts = payload.get("alerts") or []
    for item in alerts:
        labels = dict(item.get("labels") or {})
        annotations = dict(item.get("annotations") or {})
        status = item.get("status") or payload.get("status") or "firing"
        if status not in {"firing", "resolved"}:
            status = "firing" if status != "resolved" else "resolved"
        name = labels.get("alertname") or annotations.get("summary") or "alert"
        fingerprint = item.get("fingerprint") or _fp("am", name, json.dumps(labels, sort_keys=True))
        occurred = item.get("startsAt") if status == "firing" else item.get("endsAt") or item.get("startsAt")
        yield {
            "source": "alertmanager",
            "fingerprint": str(fingerprint),
            "external_id": str(fingerprint),
            "name": name,
            "summary": annotations.get("description") or annotations.get("summary"),
            "status": status,
            "severity": labels.get("severity") or "warning",
            "labels": {**labels, **{k: v for k, v in annotations.items() if k not in labels}},
            "raw": item,
            "occurred_at": occurred,
        }


def iter_zabbix(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Accept a single event or a list under `events` / `problems`.

    Common Zabbix webhook fields: event_id, event_value (1=problem, 0=ok),
    event_name / event_nseverity / host / hostname / tags.
    """
    events = payload.get("events") or payload.get("problems")
    if events is None:
        events = [payload]
    for item in events:
        value = str(item.get("event_value", item.get("value", "1")))
        status = "resolved" if value in {"0", "OK", "ok", "resolved"} else "firing"
        host = item.get("host") or item.get("hostname") or item.get("device") or ""
        name = item.get("event_name") or item.get("name") or item.get("trigger") or "Zabbix event"
        event_id = str(item.get("event_id") or item.get("id") or _fp("zbx", name, host))
        # Fingerprint on trigger+host so resolve/problem pair up; event_id changes
        # between problem and recovery in some templates, trigger_id does not.
        trigger_id = str(item.get("trigger_id") or item.get("triggerid") or event_id)
        fingerprint = _fp("zbx", trigger_id, host, name)
        labels = {
            "host": host,
            "instance": host,
            "severity": str(item.get("event_nseverity") or item.get("severity") or "warning"),
        }
        for tag in item.get("tags") or item.get("event_tags") or []:
            if isinstance(tag, dict) and tag.get("tag"):
                labels[str(tag["tag"])] = str(tag.get("value") or "")
            elif isinstance(tag, str) and "=" in tag:
                k, _, v = tag.partition("=")
                labels[k] = v
        # Promote well-known extra fields into labels for topology matching.
        for key in ("circuit", "site", "device", "bundle", "instance"):
            if item.get(key):
                labels[key] = item[key]
        severity = labels.get("severity") or "warning"
        yield {
            "source": "zabbix",
            "fingerprint": fingerprint,
            "external_id": event_id,
            "name": name,
            "summary": item.get("event_opdata") or item.get("message") or item.get("summary"),
            "status": status,
            "severity": str(severity),
            "labels": labels,
            "raw": item,
            "occurred_at": item.get("event_time") or item.get("clock"),
        }


def iter_generic(payload: dict[str, Any] | GenericAlertIn) -> Iterator[dict[str, Any]]:
    if isinstance(payload, GenericAlertIn):
        data = payload.model_dump()
    else:
        # Allow a batch under `alerts`.
        if "alerts" in payload and isinstance(payload["alerts"], list) and "status" not in payload:
            for item in payload["alerts"]:
                yield from iter_generic(item)
            return
        data = dict(payload)
    status = data.get("status") or "firing"
    if status in {"ok", "OK", "0"}:
        status = "resolved"
    name = data.get("name") or "generic alert"
    labels = dict(data.get("labels") or {})
    target = data.get("target")
    if target:
        typ = target.get("type") if isinstance(target, dict) else getattr(target, "type", None)
        slug = target.get("slug") if isinstance(target, dict) else getattr(target, "slug", None)
        if typ and slug:
            labels[typ] = slug
    fingerprint = data.get("fingerprint") or _fp(
        data.get("source") or "generic",
        str(data.get("external_id") or ""),
        name,
        json.dumps(labels, sort_keys=True),
    )
    yield {
        "source": data.get("source") or "generic",
        "fingerprint": fingerprint,
        "external_id": data.get("external_id"),
        "name": name,
        "summary": data.get("summary"),
        "status": status,
        "severity": data.get("severity") or "warning",
        "labels": labels,
        "raw": data,
        "occurred_at": data.get("occurred_at"),
    }


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):

        # Zabbix clock is often epoch seconds.
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None
