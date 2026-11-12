from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from rootfold import (
    __version__,
    exporters,
    gate,
    graph,
    handover,
    importer,
    lab,
    netbox,
    reports,
    runbooks,
)
from rootfold import engine as eng
from rootfold.auth import (
    authenticate_operator,
    create_access_token,
    generate_api_key,
    hash_api_key,
    require_operator,
    require_webhook_key,
)
from rootfold.exporters import ExportError
from rootfold.gate import GateError
from rootfold.handover import HandoverError
from rootfold.models import (
    ApiKey,
    Bundle,
    Circuit,
    Device,
    Handover,
    Incident,
    MaintenanceWindow,
    Operator,
    Site,
    TicketExport,
)
from rootfold.netbox import NetBoxError
from rootfold.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    BlastRadiusOut,
    ChecksIn,
    ExportIn,
    GateIn,
    HandoverAckIn,
    HandoverCloseIn,
    HandoverOut,
    HealthOut,
    ImportResult,
    IncidentDetail,
    IngestResult,
    LoginRequest,
    MaintenanceIn,
    MeOut,
    Ref,
    TokenResponse,
)
from rootfold.serialize import alert_out, handover_out, incident_out, maintenance_out
from rootfold.service import ingest_source, resolve_ref

public = APIRouter()
ops = APIRouter(dependencies=[Depends(require_operator)])
hooks = APIRouter(dependencies=[Depends(require_webhook_key)])


def _db(request: Request) -> Session:
    return request.state.db


def _example_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    path = root / "examples" / "carpathian-carrier.yaml"
    if not path.exists():
        path = Path("/examples/carpathian-carrier.yaml")
    return path


@public.get("/healthz", response_model=HealthOut, tags=["ops"], summary="Liveness / readiness")
@public.get("/api/healthz", response_model=HealthOut, tags=["ops"], include_in_schema=False)
def healthz(request: Request) -> HealthOut:
    settings = request.app.state.settings
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=__version__,
        lab_mode=settings.lab_mode,
        time=request.app.state.clock.now(),
    )


@public.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest, request: Request) -> TokenResponse:
    db = _db(request)
    op = authenticate_operator(db, body.username, body.password)
    if op is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(op.username, request.app.state.settings, request.app.state.clock.now())
    return TokenResponse(access_token=token)


@ops.get("/api/auth/me", response_model=MeOut, tags=["auth"])
def me(op: Operator = Depends(require_operator)) -> MeOut:
    return MeOut(username=op.username, role=op.role)


@ops.post("/api/auth/api-keys", response_model=ApiKeyCreated, tags=["auth"])
def create_key(body: ApiKeyCreate, request: Request) -> ApiKeyCreated:
    db = _db(request)
    raw = generate_api_key()
    now = request.app.state.clock.now()
    row = ApiKey(
        name=body.name,
        prefix=raw[:10],
        key_hash=hash_api_key(raw),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return ApiKeyCreated(id=row.id, name=row.name, prefix=row.prefix, key=raw)


@ops.get("/api/auth/api-keys", response_model=list[ApiKeyOut], tags=["auth"])
def list_keys(request: Request) -> list[ApiKeyOut]:
    db = _db(request)
    rows = db.query(ApiKey).order_by(ApiKey.id.asc()).all()
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            prefix=r.prefix,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked=r.revoked,
        )
        for r in rows
    ]


@ops.post("/api/auth/api-keys/{key_id}/revoke", tags=["auth"])
def revoke_key(key_id: int, request: Request) -> dict:
    row = _db(request).get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    row.revoked = True
    return {"ok": True, "id": key_id}


@ops.post("/api/topology/import", response_model=ImportResult, tags=["topology"])
async def import_topology(
    request: Request,
    file: UploadFile | None = File(default=None),
) -> ImportResult:
    db = _db(request)
    if file is not None:
        raw = (await file.read()).decode("utf-8")
        stats = importer.import_any(db, raw, file.filename or "topology.yaml")
    else:
        body = await request.json()
        if "yaml" in body:
            stats = importer.import_yaml_text(db, body["yaml"])
        else:
            stats = importer.import_payload(db, body)
    return ImportResult(**stats)


@ops.post("/api/topology/import-example", response_model=ImportResult, tags=["topology"])
def import_example(request: Request) -> ImportResult:
    root = Path(__file__).resolve().parents[3]
    path = root / "examples" / "carpathian-carrier.yaml"
    if not path.exists():
        # Running from a wheel / docker: also try /examples
        path = Path("/examples/carpathian-carrier.yaml")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Example topology file not found")
    stats = importer.import_yaml_path(_db(request), path)
    return ImportResult(**stats)



@ops.post("/api/topology/import-netbox", tags=["topology"], summary="Import topology from NetBox")
def import_netbox(request: Request, fixture: str | None = None) -> dict:
    """Pull sites, devices, cables and circuits from NetBox (or a recorded fixture in lab mode)."""
    db = _db(request)
    settings = request.app.state.settings
    fixture_path = fixture if (fixture and settings.lab_mode) else settings.netbox_fixture
    if fixture_path:
        path = Path(fixture_path).resolve()
        repo = Path(__file__).resolve().parents[3]
        if repo not in path.parents and path.parent != repo:
            raise HTTPException(status_code=400, detail="Fixture path must be inside the Rootfold repo")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Fixture file not found")
        return netbox.import_from_fixture(db, path)
    if not settings.netbox_url or not settings.netbox_token:
        raise HTTPException(
            status_code=400,
            detail="Set ROOTFOLD_NETBOX_URL and ROOTFOLD_NETBOX_TOKEN, or pass a fixture in lab mode",
        )
    try:
        return netbox.import_from_netbox(db, settings)
    except NetBoxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@ops.get("/api/topology/sites", tags=["topology"])
def list_sites(request: Request) -> list[dict]:
    return [
        {"id": s.id, "slug": s.slug, "name": s.name, "region": s.region, "notes": s.notes}
        for s in _db(request).query(Site).order_by(Site.slug).all()
    ]


@ops.get("/api/topology/devices", tags=["topology"])
def list_devices(request: Request) -> list[dict]:
    db = _db(request)
    out = []
    for d in db.query(Device).order_by(Device.slug).all():
        out.append(
            {
                "id": d.id,
                "slug": d.slug,
                "name": d.name,
                "role": d.role,
                "site": d.site.slug if d.site else None,
                "management_ip": d.management_ip,
                "vendor": d.vendor,
                "model": d.model,
            }
        )
    return out


@ops.get("/api/topology/circuits", tags=["topology"])
def list_circuits(request: Request) -> list[dict]:
    db = _db(request)
    sites = {s.id: s.slug for s in db.query(Site).all()}
    devices = {d.id: d.slug for d in db.query(Device).all()}
    out = []
    for c in db.query(Circuit).order_by(Circuit.slug).all():
        out.append(
            {
                "id": c.id,
                "slug": c.slug,
                "name": c.name,
                "media": c.media,
                "a_site": sites.get(c.a_site_id),
                "z_site": sites.get(c.z_site_id),
                "a_device": devices.get(c.a_device_id) if c.a_device_id else None,
                "z_device": devices.get(c.z_device_id) if c.z_device_id else None,
                "capacity_mbps": c.capacity_mbps,
                "customer": c.customer,
                "vendor_circuit_id": c.vendor_circuit_id,
            }
        )
    return out


@ops.get("/api/topology/bundles", tags=["topology"])
def list_bundles(request: Request) -> list[dict]:
    db = _db(request)
    devices = {d.id: d.slug for d in db.query(Device).all()}
    out = []
    for b in db.query(Bundle).order_by(Bundle.slug).all():
        members = graph.bundle_members(db, b.id)
        out.append(
            {
                "id": b.id,
                "slug": b.slug,
                "name": b.name,
                "device": devices.get(b.device_id),
                "members": [graph.slug_of(db, typ, oid) for typ, oid in members],
            }
        )
    return out


@ops.get("/api/topology/blast-radius", response_model=BlastRadiusOut, tags=["topology"])
def get_blast_radius(
    request: Request,
    object_type: str = Query(..., alias="type"),
    slug: str = Query(...),
) -> BlastRadiusOut:
    db = _db(request)
    try:
        typ, oid = resolve_ref(db, object_type, slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    data = graph.blast_radius(db, typ, oid)
    return BlastRadiusOut(
        root=Ref(type=typ, slug=data["root"]["slug"]),
        sites=data["sites"],
        devices=data["devices"],
        circuits=data["circuits"],
        bundles=data["bundles"],
        customers=data["customers"],
    )


def _ingest(request: Request, source: str, payload: dict) -> IngestResult:
    db = _db(request)
    alerts, incidents, suppressed, _actions = ingest_source(
        db, source, payload, request.app.state.clock, request.app.state.settings
    )
    return IngestResult(
        alerts=[alert_out(db, a) for a in alerts],
        incidents=[incident_out(db, i) for i in incidents],
        suppressed=suppressed,
        message=f"ingested {len(alerts)} alert(s) from {source}",
    )


@hooks.post("/api/ingest/alertmanager", response_model=IngestResult, tags=["ingest"])
async def ingest_am(request: Request) -> IngestResult:
    return _ingest(request, "alertmanager", await request.json())


@hooks.post("/api/ingest/zabbix", response_model=IngestResult, tags=["ingest"])
async def ingest_zbx(request: Request) -> IngestResult:
    return _ingest(request, "zabbix", await request.json())


@hooks.post("/api/ingest/generic", response_model=IngestResult, tags=["ingest"])
async def ingest_generic(request: Request) -> IngestResult:
    return _ingest(request, "generic", await request.json())


@ops.get("/api/incidents", tags=["incidents"])
def list_incidents(
    request: Request,
    status: str | None = None,
    kind: str | None = None,
) -> list:
    db = _db(request)
    q = db.query(Incident).order_by(Incident.id.desc())
    if status:
        q = q.filter(Incident.status == status)
    if kind:
        q = q.filter(Incident.kind == kind)
    return [incident_out(db, i) for i in q.all()]


@ops.get("/api/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
def get_incident(incident_id: int, request: Request) -> IncidentDetail:
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident_out(db, inc, detail=True)  # type: ignore[return-value]


@ops.put("/api/incidents/{incident_id}/gate", tags=["incidents"], summary="Fill the L1 quality gate")
def put_gate(
    incident_id: int,
    body: GateIn,
    request: Request,
    op: Operator = Depends(require_operator),
):
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        gate.apply_gate(
            db,
            inc,
            impact=body.impact,
            urgency=body.urgency,
            checks=body.checks,
            notes=body.notes,
            actor=op.username,
            now=request.app.state.clock.now(),
        )
    except GateError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc
    return incident_out(db, inc, detail=True)


def _operator_action(incident_id: int, request: Request, op: Operator, action: str):
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    now = request.app.state.clock.now()
    try:
        if action == "escalate":
            gate.escalate(db, inc, actor=op.username, now=now)
        else:
            gate.operator_resolve(db, inc, actor=op.username, now=now)
    except GateError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc
    return incident_out(db, inc, detail=True)


@ops.post("/api/incidents/{incident_id}/escalate", tags=["incidents"])
def escalate_incident(
    incident_id: int, request: Request, op: Operator = Depends(require_operator)
):
    return _operator_action(incident_id, request, op, "escalate")


@ops.post("/api/incidents/{incident_id}/resolve", tags=["incidents"])
def resolve_incident(
    incident_id: int, request: Request, op: Operator = Depends(require_operator)
):
    return _operator_action(incident_id, request, op, "resolve")




@ops.get("/api/runbooks", tags=["runbooks"])
def list_runbooks() -> list[dict]:
    return runbooks.library()


@ops.get("/api/runbooks/{runbook_id}", tags=["runbooks"])
def get_runbook(runbook_id: str) -> dict:
    book = runbooks.get_runbook(runbook_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return book.as_dict()


@ops.get("/api/incidents/{incident_id}/runbooks", tags=["runbooks"])
def incident_runbooks(incident_id: int, request: Request) -> dict:
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    attached = runbooks.attach_runbooks(db, inc)
    return {"incident_id": inc.id, "public_ref": inc.public_ref, "runbooks": attached}


@ops.post("/api/incidents/{incident_id}/checks", tags=["runbooks"], summary="Tick runbook checks into the L1 gate")
def tick_checks(
    incident_id: int,
    body: ChecksIn,
    request: Request,
    op: Operator = Depends(require_operator),
):
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    runbooks.add_checks(
        db, inc, body.checks, actor=op.username, now=request.app.state.clock.now()
    )
    return incident_out(db, inc, detail=True)


@ops.get("/api/incidents/{incident_id}/export", tags=["export"])
def list_exports(incident_id: int, request: Request) -> dict:
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    settings = request.app.state.settings
    history = (
        db.query(TicketExport)
        .filter(TicketExport.incident_id == incident_id)
        .order_by(TicketExport.id.desc())
        .all()
    )
    return {
        "incident_id": incident_id,
        "public_ref": inc.public_ref,
        "jira_configured": exporters.jira_configured(settings),
        "servicenow_configured": exporters.snow_configured(settings),
        "history": [exporters.export_out(row) for row in history],
    }


@ops.post("/api/incidents/{incident_id}/export", tags=["export"], summary="Export to Jira or ServiceNow")
def export_incident(
    incident_id: int,
    body: ExportIn,
    request: Request,
    op: Operator = Depends(require_operator),
) -> dict:
    db = _db(request)
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        row = exporters.export_incident(
            db,
            inc,
            request.app.state.settings,
            body.backend,
            actor=op.username,
            now=request.app.state.clock.now(),
            dry_run=body.dry_run,
        )
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return exporters.export_out(row)


@ops.get("/api/alerts", tags=["incidents"])
def list_alerts(request: Request, status: str | None = None) -> list:
    db = _db(request)
    from rootfold.models import Alert

    q = db.query(Alert).order_by(Alert.id.desc())
    if status:
        q = q.filter(Alert.status == status)
    return [alert_out(db, a) for a in q.all()]


@ops.post("/api/maintenance", tags=["maintenance"])
def create_maintenance(body: MaintenanceIn, request: Request, op: Operator = Depends(require_operator)):
    db = _db(request)
    try:
        typ, oid = resolve_ref(db, body.object.type, body.object.slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    row = MaintenanceWindow(
        object_type=typ,
        object_id=oid,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
        created_by=op.username,
    )
    db.add(row)
    db.flush()
    return maintenance_out(db, row)


@ops.get("/api/maintenance", tags=["maintenance"])
def list_maintenance(request: Request) -> list:
    db = _db(request)
    rows = db.query(MaintenanceWindow).order_by(MaintenanceWindow.starts_at.desc()).all()
    return [maintenance_out(db, r) for r in rows]


@ops.delete("/api/maintenance/{window_id}", tags=["maintenance"])
def delete_maintenance(window_id: int, request: Request) -> dict:
    db = _db(request)
    row = db.get(MaintenanceWindow, window_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Window not found")
    db.delete(row)
    return {"ok": True}


@ops.post("/api/ops/sweep", tags=["ops"], summary="Run due recovery sweeps")
def run_sweep(request: Request) -> dict:
    db = _db(request)
    created = eng.run_due_sweeps(
        db, request.app.state.clock, request.app.state.settings.recovery_sweep_seconds
    )
    return {
        "leftovers": [incident_out(db, i) for i in created],
        "count": len(created),
    }


@ops.get("/api/ops/settings", tags=["ops"])
def get_runtime_settings(request: Request) -> dict:
    db = _db(request)
    default = request.app.state.settings.recovery_sweep_seconds
    return {
        "recovery_sweep_seconds": eng.sweep_delay_seconds(db, default),
        "sweep_interval_seconds": request.app.state.settings.sweep_interval_seconds,
        "lab_mode": request.app.state.settings.lab_mode,
    }


@ops.put("/api/ops/settings", tags=["ops"])
def put_runtime_settings(
    request: Request,
    recovery_sweep_seconds: int | None = Query(default=None, ge=0),
    sweep_interval_seconds: int | None = Query(default=None, ge=0),
) -> dict:
    db = _db(request)
    if recovery_sweep_seconds is not None:
        eng.set_sweep_delay(db, recovery_sweep_seconds)
    if sweep_interval_seconds is not None:
        request.app.state.settings.sweep_interval_seconds = sweep_interval_seconds
    default = request.app.state.settings.recovery_sweep_seconds
    return {
        "recovery_sweep_seconds": eng.sweep_delay_seconds(db, default),
        "sweep_interval_seconds": request.app.state.settings.sweep_interval_seconds,
        "lab_mode": request.app.state.settings.lab_mode,
        "note": "A new sweep_interval_seconds takes effect after process restart",
    }

@ops.post("/api/handover/close", response_model=HandoverOut, tags=["handover"])
def close_handover(
    request: Request,
    body: HandoverCloseIn | None = None,
    op: Operator = Depends(require_operator),
) -> HandoverOut:
    notes = body.notes if body else None
    try:
        row = handover.close_shift(
            _db(request), actor=op.username, now=request.app.state.clock.now(), notes=notes
        )
    except HandoverError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return handover_out(row)


@ops.get("/api/handover/pending", response_model=HandoverOut | None, tags=["handover"])
def pending_handover(request: Request) -> HandoverOut | None:
    row = handover.pending(_db(request))
    return handover_out(row) if row else None


@ops.get("/api/handover", response_model=list[HandoverOut], tags=["handover"])
def list_handovers(request: Request) -> list[HandoverOut]:
    rows = _db(request).query(Handover).order_by(Handover.id.desc()).all()
    return [handover_out(r) for r in rows]


@ops.get("/api/handover/{handover_id}", response_model=HandoverOut, tags=["handover"])
def get_handover(handover_id: int, request: Request) -> HandoverOut:
    row = _db(request).get(Handover, handover_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Handover not found")
    return handover_out(row)


@ops.post("/api/handover/{handover_id}/ack", response_model=HandoverOut, tags=["handover"])
def ack_handover(
    handover_id: int,
    request: Request,
    body: HandoverAckIn | None = None,
    op: Operator = Depends(require_operator),
) -> HandoverOut:
    db = _db(request)
    row = db.get(Handover, handover_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Handover not found")
    try:
        row = handover.acknowledge(
            db,
            row,
            actor=op.username,
            now=request.app.state.clock.now(),
            notes=body.notes if body else None,
        )
    except HandoverError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return handover_out(row)


@ops.get("/api/reports/availability", tags=["reports"], summary="Monthly availability by circuit, site and customer")
def availability_report(
    request: Request,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    format: str = Query(default="json"),
):
    now = request.app.state.clock.now()
    year = year or now.year
    month = month or now.month
    try:
        report = reports.build_availability(
            _db(request),
            year=year,
            month=month,
            now=now,
            settings=request.app.state.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if format == "csv":
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(
            reports.to_csv(report),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="rootfold-availability-{year}-{month:02d}.csv"'
            },
        )
    if format not in {"json", "csv"}:
        raise HTTPException(status_code=422, detail="format must be json or csv")
    return report


@ops.get("/api/lab/scenarios", tags=["lab"])
def list_scenarios() -> list[dict]:
    return [
        {"id": key, "title": val["title"], "summary": val["summary"]}
        for key, val in lab.SCENARIOS.items()
    ]


@ops.post("/api/lab/reset", tags=["lab"])
def lab_reset(request: Request, reimport: bool = True) -> dict:
    stats = lab.reset_lab(_db(request), reimport=reimport, example=_example_path())
    return {"ok": True, **stats}


@ops.post("/api/lab/inject/{scenario}", tags=["lab"])
def lab_inject(scenario: str, request: Request) -> dict:
    try:
        return lab.inject(
            _db(request), scenario, request.app.state.clock, request.app.state.settings
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@ops.get("/api/topology/graph", tags=["topology"])
def topology_graph(request: Request) -> dict:
    return lab.topology_graph(_db(request))


