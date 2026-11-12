from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from rootfold import __version__
from rootfold.api.routes import hooks, ops, public
from rootfold.auth import hash_api_key, hash_password
from rootfold.clock import Clock
from rootfold.config import Settings, get_settings
from rootfold.db import ensure_schema, make_engine, make_session_factory
from rootfold.logging import setup_logging
from rootfold.models import ApiKey, Operator
from rootfold.scheduler import scheduler_loop

log = logging.getLogger("rootfold")

DISCLAIMER = (
    "Rootfold's public/demo data is a simulated regional-carrier lab, not a production network. "
    "Self-host to ingest your own Alertmanager or Zabbix webhooks against a topology you import."
)

def seed_defaults(db: Session, settings: Settings, clock: Clock) -> None:
    for username, password, role, label in (
        (settings.admin_username, settings.admin_password, "admin", "admin"),
        (settings.night_username, settings.night_password, "operator", "night"),
    ):
        if username and db.query(Operator).filter(Operator.username == username).one_or_none() is None:
            db.add(Operator(username=username, password_hash=hash_password(password), role=role))
            log.info("seeded %s operator", label)
    existing = db.query(ApiKey).filter(ApiKey.prefix == settings.webhook_key[:10]).one_or_none()
    hashed = hash_api_key(settings.webhook_key)
    if db.query(ApiKey).filter(ApiKey.key_hash == hashed).one_or_none() is None and existing is None:
        now = clock.now()
        db.add(
            ApiKey(
                name="lab-webhook",
                prefix=settings.webhook_key[:10],
                key_hash=hashed,
                created_at=now,
            )
        )
        log.info("seeded lab webhook API key")
    db.commit()


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    database_url: str | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or Clock()
    setup_logging(settings.log_level)
    url = database_url or settings.database_url
    engine = make_engine(url)
    ensure_schema(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        seed_defaults(db, settings, clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("rootfold starting version=%s lab_mode=%s", __version__, settings.lab_mode)
        task = None
        if settings.sweep_interval_seconds > 0:
            task = asyncio.create_task(scheduler_loop(app), name="rootfold-sweep")
            app.state.sweep_task = task
        else:
            app.state.sweep_task = None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            engine.dispose()

    app = FastAPI(
        title="Rootfold",
        version=__version__,
        description=(
            "Topology-aware incident layer for NOCs. Ingest alerts, fold them by circuit/site/LACP "
            "dependencies, and run a recovery sweep so leftover child failures are not auto-closed.\n\n"
            f"**Disclaimer:** {DISCLAIMER}"
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = engine
    app.state.session_factory = factory

    class DBMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            db = factory()
            request.state.db = db
            try:
                response = await call_next(request)
                db.commit()
                return response
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    app.add_middleware(DBMiddleware)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        response = await call_next(request)
        log.info(
            "request",
            extra={"method": request.method, "path": request.url.path, "status": response.status_code},
        )
        return response

    app.include_router(public)
    app.include_router(ops)
    app.include_router(hooks)

    static_dir = Path(__file__).resolve().parent / "static"

    @app.get("/", include_in_schema=False)
    def landing() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/api", include_in_schema=False)
    def api_index() -> JSONResponse:
        return JSONResponse(
            {
                "name": "Rootfold",
                "version": __version__,
                "docs": "/api/docs",
                "disclaimer": DISCLAIMER,
            }
        )

    return app


app = create_app()


def cli() -> None:
    import argparse
    import json
    import sys

    import uvicorn

    parser = argparse.ArgumentParser(prog="rootfold", description="Rootfold NOC incident layer")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Run the API and operator console (default)")
    nb = sub.add_parser("import-netbox", help="Import topology from NetBox or a recorded fixture")
    nb.add_argument("--fixture", help="Path to recorded NetBox JSON (offline, no HTTP)")
    nb.add_argument("--url", help="NetBox base URL (overrides ROOTFOLD_NETBOX_URL)")
    nb.add_argument("--token", help="NetBox API token (overrides ROOTFOLD_NETBOX_TOKEN)")
    args = parser.parse_args()

    if args.cmd in (None, "serve"):
        settings = get_settings()
        Path("data").mkdir(exist_ok=True)
        uvicorn.run(
            "rootfold.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level=settings.log_level.lower(),
        )
        return

    if args.cmd == "import-netbox":
        from rootfold.db import ensure_schema, make_engine, make_session_factory
        from rootfold.netbox import NetBoxError, import_from_fixture, import_from_netbox

        settings = get_settings()
        if args.url:
            settings.netbox_url = args.url
        if args.token:
            settings.netbox_token = args.token
        if args.fixture:
            settings.netbox_fixture = args.fixture
        Path("data").mkdir(exist_ok=True)
        engine = make_engine(settings.database_url)
        ensure_schema(engine)
        factory = make_session_factory(engine)
        try:
            with factory() as db:
                if settings.netbox_fixture:
                    stats = import_from_fixture(db, Path(settings.netbox_fixture))
                else:
                    stats = import_from_netbox(db, settings)
                db.commit()
        except (NetBoxError, OSError, ValueError) as exc:
            print(f"import-netbox failed: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(stats, indent=2))
        return


if __name__ == "__main__":
    cli()
