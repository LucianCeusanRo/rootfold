from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_path(url: str) -> None:
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if path not in {":memory:", ""} and not path.startswith("file:"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str, *, echo: bool = False) -> Engine:
    _ensure_sqlite_path(url)
    kwargs: dict = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _rec) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def session_dep(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


INCIDENT_NEW_COLUMNS = {
    "impact": "VARCHAR(40)",
    "urgency": "VARCHAR(20)",
    "checks": "JSON",
    "l1_notes": "TEXT",
    "gate_completed_at": "DATETIME",
    "gate_completed_by": "VARCHAR(80)",
    "escalated_at": "DATETIME",
    "escalated_by": "VARCHAR(80)",
    "resolved_by": "VARCHAR(80)",
}


def ensure_schema(engine: Engine) -> None:
    """create_all plus additive SQLite column upgrades for existing lab DBs."""
    from sqlalchemy import inspect, text

    Base.metadata.create_all(engine)
    insp = inspect(engine)
    if "incidents" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("incidents")}
    with engine.begin() as conn:
        for name, typ in INCIDENT_NEW_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE incidents ADD COLUMN {name} {typ}"))
