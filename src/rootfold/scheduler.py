"""Background recovery-sweep loop. Interval 0 disables it; POST /api/ops/sweep still works."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from rootfold.engine import run_due_sweeps

log = logging.getLogger("rootfold.scheduler")


def tick_sweeps(app: FastAPI) -> int:
    """Run due sweeps once. Returns how many leftover incidents were opened."""
    factory = app.state.session_factory
    db = factory()
    try:
        created = run_due_sweeps(
            db, app.state.clock, app.state.settings.recovery_sweep_seconds
        )
        db.commit()
        if created:
            log.info("sweep tick opened %s leftover incident(s)", len(created))
        return len(created)
    except Exception:
        db.rollback()
        log.exception("sweep tick failed")
        raise
    finally:
        db.close()


async def scheduler_loop(app: FastAPI) -> None:
    interval = int(getattr(app.state.settings, "sweep_interval_seconds", 0) or 0)
    if interval <= 0:
        return
    log.info("recovery-sweep scheduler started interval=%ss", interval)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                tick_sweeps(app)
            except Exception:
                # Already logged; keep the loop alive.
                pass
    except asyncio.CancelledError:
        log.info("recovery-sweep scheduler stopped")
        raise
