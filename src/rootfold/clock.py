"""Injectable clock so recovery-sweep tests can advance time without sleeping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class Clock:
    """Real wall clock in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests."""

    def __init__(self, at: datetime | None = None) -> None:
        self._t = at or datetime(2026, 9, 13, 4, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> datetime:
        self._t = self._t + timedelta(seconds=seconds)
        return self._t

    def set(self, at: datetime) -> None:
        self._t = at
