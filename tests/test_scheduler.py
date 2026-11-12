from helpers import clear, fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.engine import run_due_sweeps
from rootfold.models import Incident
from rootfold.scheduler import tick_sweeps


def test_tick_sweeps_runs_due_recovery(
    app, db, topology, clock: FrozenClock, settings: Settings
) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-backup", "device", "Backup job failed")
    clock.advance(5)
    clear(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    db.commit()
    # Not due yet.
    assert tick_sweeps(app) == 0
    assert open_incidents(db)[0].status == "sweep_pending"

    clock.advance(settings.recovery_sweep_seconds)
    opened = tick_sweeps(app)
    assert opened == 1
    db.expire_all()
    leftovers = db.query(Incident).filter(Incident.kind == "leftover").all()
    assert len(leftovers) == 1
    assert leftovers[0].status == "open"


def test_scheduler_disabled_in_tests(app, settings: Settings) -> None:
    assert settings.sweep_interval_seconds == 0
    assert getattr(app.state, "sweep_task", None) is None
    # Manual sweep route still exists as the on-demand path.
    assert callable(run_due_sweeps)
