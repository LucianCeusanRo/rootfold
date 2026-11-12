from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from helpers import clear, fire
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.engine import run_due_sweeps
from rootfold.models import Circuit, Incident
from rootfold.reports import build_availability, month_window, to_csv, union_seconds

SEPT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
PERIOD = 30 * 24 * 3600  # September 2026


def test_month_window_september_2026() -> None:
    start, end = month_window(2026, 9)
    assert start == datetime(2026, 9, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, tzinfo=UTC)
    assert (end - start).total_seconds() == PERIOD


def test_union_merges_overlap() -> None:
    start, end = month_window(2026, 9)
    a = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    b = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
    c = datetime(2026, 9, 10, 12, 30, tzinfo=UTC)
    d = datetime(2026, 9, 10, 13, 30, tzinfo=UTC)
    assert union_seconds([(a, b), (c, d)], start, end) == 90 * 60


def _row(report: dict, slug: str) -> dict:
    return next(r for r in report["rows"] if r["slug"] == slug)


def test_sixty_minute_outage_is_an_sla_breach(
    db: Session, topology, clock: FrozenClock, settings: Settings
) -> None:
    clock.set(SEPT)
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clock.advance(3600)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clock.advance(settings.recovery_sweep_seconds)
    run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    report = build_availability(db, year=2026, month=9, now=clock.now(), settings=settings)
    row = _row(report, "cir-ons-drm-mw")
    assert row["scope"] == "circuit"
    # Downtime includes the recovery-sweep wait; MTTR is opened→resolved.
    expected = 3600 + settings.recovery_sweep_seconds
    assert row["downtime_seconds"] == expected
    assert row["mttr_seconds"] == expected
    assert row["uptime_percent"] == round(100 * (1 - expected / PERIOD), 4)
    assert row["incident_count"] == 1
    assert row["sla_percent"] == 99.9
    assert row["sla_breach"] is True
    # Blast radius includes the far-end site and the customer tail.
    assert _row(report, "drm")["sla_breach"] is True
    assert _row(report, "Forestworks SRL")["scope"] == "customer"
    assert _row(report, "Forestworks SRL")["incident_count"] == 1
    # Untouched fibre stays at 100%.
    clean = _row(report, "cir-bcu-rmn")
    assert clean["uptime_percent"] == 100.0
    assert clean["sla_breach"] is False
    assert clean["incident_count"] == 0
    assert clean["mttr_seconds"] is None


def test_short_outage_does_not_breach(
    db: Session, topology, clock: FrozenClock, settings: Settings
) -> None:
    clock.set(SEPT)
    fire(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    clock.advance(600)
    clear(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    report = build_availability(db, year=2026, month=9, now=clock.now(), settings=settings)
    row = _row(report, "cir-bcu-ons")
    assert row["downtime_seconds"] == 600
    assert row["uptime_percent"] == 99.9769
    assert row["sla_breach"] is False


def test_two_outages_on_one_circuit_add_when_separate(
    db: Session, topology, clock: FrozenClock, settings: Settings
) -> None:
    clock.set(SEPT)
    fire(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    clock.advance(1800)
    clear(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    clock.advance(settings.recovery_sweep_seconds)
    run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    clock.advance(1800)
    fire(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    clock.advance(1800)
    clear(db, clock, settings, "cir-bcu-ons", "circuit", "Fiber LOS")
    clock.advance(settings.recovery_sweep_seconds)
    run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    report = build_availability(db, year=2026, month=9, now=clock.now(), settings=settings)
    row = _row(report, "cir-bcu-ons")
    assert row["incident_count"] == 2
    assert row["downtime_seconds"] == 2 * (1800 + settings.recovery_sweep_seconds)
    assert row["mttr_seconds"] == 1800 + settings.recovery_sweep_seconds


def test_overlapping_incidents_use_union_not_sum(db: Session, topology, clock: FrozenClock, settings: Settings) -> None:
    circuit = db.query(Circuit).filter(Circuit.slug == "cir-bcu-rmn").one()
    start = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    db.add(
        Incident(
            public_ref="INC-TEST-1",
            status="resolved",
            title="First",
            severity="critical",
            kind="outage",
            root_type="circuit",
            root_id=circuit.id,
            blast_radius={"circuits": ["cir-bcu-rmn"], "sites": [], "customers": []},
            opened_at=start,
            resolved_at=start.replace(hour=13),
        )
    )
    db.add(
        Incident(
            public_ref="INC-TEST-2",
            status="resolved",
            title="Second",
            severity="critical",
            kind="outage",
            root_type="circuit",
            root_id=circuit.id,
            blast_radius={"circuits": ["cir-bcu-rmn"], "sites": [], "customers": []},
            opened_at=start.replace(minute=30),
            resolved_at=start.replace(hour=13, minute=30),
        )
    )
    db.flush()
    report = build_availability(db, year=2026, month=9, now=clock.now(), settings=settings)
    row = _row(report, "cir-bcu-rmn")
    assert row["downtime_seconds"] == 90 * 60
    assert row["incident_count"] == 2


def test_api_json_and_csv(
    client: TestClient, auth_headers: dict, db: Session, topology, clock: FrozenClock, settings: Settings
) -> None:
    clock.set(SEPT)
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clock.advance(3600)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    db.commit()

    json_r = client.get(
        "/api/reports/availability",
        headers=auth_headers,
        params={"year": 2026, "month": 9},
    )
    assert json_r.status_code == 200, json_r.text
    body = json_r.json()
    assert body["year"] == 2026 and body["month"] == 9
    assert body["breach_count"] >= 1
    assert _row(body, "cir-ons-drm-mw")["sla_breach"] is True

    csv_r = client.get(
        "/api/reports/availability",
        headers=auth_headers,
        params={"year": 2026, "month": 9, "format": "csv"},
    )
    assert csv_r.status_code == 200, csv_r.text
    assert "text/csv" in csv_r.headers["content-type"]
    text = csv_r.text
    assert text.startswith("scope,slug,name,")
    assert "cir-ons-drm-mw" in text
    assert to_csv(body).splitlines()[0] == text.splitlines()[0]

    bad = client.get(
        "/api/reports/availability",
        headers=auth_headers,
        params={"year": 2026, "month": 13},
    )
    assert bad.status_code == 422
