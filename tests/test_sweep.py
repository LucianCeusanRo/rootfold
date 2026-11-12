"""Recovery sweep — the r/networking Sept 2026 scenario.

https://www.reddit.com/r/networking/comments/1we5af4/how_do_you_stop_one_site_outage_from_turning_into/

A circuit flap produces a storm of child alerts. When the circuit returns, the
NMS auto-clears the children. One leftover failure (backup still down) must
become its own incident — it must not disappear with the parent.
"""

from helpers import clear, fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.engine import run_due_sweeps
from rootfold.models import Alert, Incident


def test_reddit_sept_2026_parent_recovers_leftover_child_becomes_new_incident(
    db, topology, clock: FrozenClock, settings: Settings
) -> None:
    # 1. Site outage: microwave hop + site devices + backup job.
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    fire(db, clock, settings, "drm-sw1", "device", "Switch unreachable")
    fire(db, clock, settings, "drm-backup", "device", "Backup job failed")
    parent = open_incidents(db)[0]
    assert parent.status == "open"
    assert db.query(Alert).filter(Alert.incident_id == parent.id).count() == 4

    # 2. The hop recovers. The NMS also auto-clears every child at the same
    #    moment — including the backup, whose "OK" is stale (it never actually
    #    completed a new run).
    clock.advance(120)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clear(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    clear(db, clock, settings, "drm-sw1", "device", "Switch unreachable")
    clear(db, clock, settings, "drm-backup", "device", "Backup job failed")

    db.refresh(parent)
    assert parent.status == "sweep_pending"
    assert parent.resolved_at is None, "parent must not close before the sweep"
    # Stale auto-clears must not count as a fresh OK.
    backups = db.query(Alert).filter(Alert.name == "Backup job failed").all()
    assert backups and backups[0].last_ok_at is None

    # 3. Wait for the stabilize window (settings default in tests is 60s).
    #    After the window, the router and switch report a *new* success.
    #    The backup never does.
    clock.advance(settings.recovery_sweep_seconds)
    clear(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    clear(db, clock, settings, "drm-sw1", "device", "Switch unreachable")
    # no fresh OK for drm-backup

    leftovers = run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    db.refresh(parent)
    assert parent.status == "resolved"
    assert parent.kind == "outage"
    assert len(leftovers) == 1
    leftover = leftovers[0]
    assert leftover.kind == "leftover"
    assert leftover.status == "open"
    assert leftover.parent_incident_id == parent.id
    assert leftover.root_type == "device"
    alert = db.query(Alert).filter(Alert.id == leftover.root_alert_id).one()
    # The backup alert was moved off the parent so it is not buried.
    assert alert.incident_id == leftover.id
    assert "backup" in leftover.title.lower() or "leftover" in leftover.title.lower()

    still_open = open_incidents(db)
    assert [i.id for i in still_open] == [leftover.id]


def test_all_children_fresh_ok_closes_cleanly(
    db, topology, clock: FrozenClock, settings: Settings
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    clock.advance(10)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    clear(db, clock, settings, "drm-rtr1", "device", "Router unreachable")  # stale
    clock.advance(settings.recovery_sweep_seconds)
    clear(db, clock, settings, "drm-rtr1", "device", "Router unreachable")  # fresh
    leftovers = run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    assert leftovers == []
    open_ = open_incidents(db)
    assert open_ == []
    parent = db.query(Incident).one()
    assert parent.status == "resolved"


def test_sweep_not_due_yet(db, topology, clock: FrozenClock, settings: Settings) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-backup", "device", "Backup job failed")
    clock.advance(5)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    leftovers = run_due_sweeps(db, clock, settings.recovery_sweep_seconds)
    assert leftovers == []
    inc = open_incidents(db)
    assert len(inc) == 1 and inc[0].status == "sweep_pending"
