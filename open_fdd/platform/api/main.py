"""Open-FDD CRUD API — data model, sites, points, equipment."""

import importlib.metadata
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.api import (
    analytics,
    bacnet,
    config as config_router,
    data_model,
    download,
    entities,
    faults,
    jobs as jobs_router,
    sites,
    points,
    equipment,
    run_fdd,
)
from open_fdd.platform.api.auth import APIKeyMiddleware
from open_fdd.platform.api.schemas import CapabilityResponse, ErrorResponse, ErrorDetail
from open_fdd.platform.realtime.ws import router as ws_router

settings = get_platform_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load in-memory graph from data_model.ttl and start background sync thread."""
    from open_fdd.platform.config import set_config_overlay
    from open_fdd.platform.graph_model import (
        get_config_from_graph,
        load_from_file,
        start_sync_thread,
        write_ttl_to_file,
    )

    load_from_file()
    set_config_overlay(get_config_from_graph())  # so get_platform_settings() sees RDF config
    write_ttl_to_file()  # ensure file exists and health state is set
    start_sync_thread()
    yield
    from open_fdd.platform.graph_model import stop_sync_thread

    stop_sync_thread()


def _app_version() -> str:
    """Open-FDD version from installed package; updates with pip install."""
    try:
        return importlib.metadata.version("open-fdd")
    except importlib.metadata.PackageNotFoundError:
        return getattr(settings, "app_version", "0.1.0")


app = FastAPI(
    title=settings.app_title,
    version=_app_version(),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "data-model",
            "description": "Export/import points, TTL generation, SPARQL validation.",
        },
        {
            "name": "download",
            "description": "Bulk export: timeseries (Excel-friendly CSV) and faults (CSV/JSON for MSI/cloud).",
        },
        {
            "name": "BACnet",
            "description": "Proxy to diy-bacnet-server (server_hello, whois_range, point_discovery, point_discovery_to_graph). Backend hits the gateway; use same host or OT LAN URL. point_discovery_to_graph updates the in-memory graph and SPARQL.",
        },
    ],
)

app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_detail_from_http_exc(status_code: int, detail) -> ErrorDetail:
    """Build ErrorDetail from HTTPException (status_code + detail)."""
    code_map = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}
    default_code = code_map.get(status_code, "ERROR")
    if isinstance(detail, dict):
        return ErrorDetail(
            code=detail.get("code", default_code),
            message=detail.get("message", str(detail)),
            details=detail.get("details"),
        )
    return ErrorDetail(
        code=default_code,
        message=str(detail) if detail else "Error",
        details=None,
    )


@app.exception_handler(HTTPException)
def _http_exception_handler(request: Request, exc: HTTPException):
    """Return uniform error schema for all HTTPException (401, 403, 404, etc.)."""
    err = _error_detail_from_http_exc(exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=err).model_dump(),
    )


@app.exception_handler(RequestValidationError)
def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return uniform error schema for 422 validation errors."""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details={"errors": exc.errors()},
            )
        ).model_dump(),
    )


@app.exception_handler(Exception)
def _unified_error_handler(request: Request, exc: Exception):
    """Catch-all for unexpected errors; re-raise so default 500 behavior or other handlers can run."""
    raise exc

app.include_router(config_router.router)
app.include_router(sites.router)
app.include_router(points.router)
app.include_router(equipment.router)
app.include_router(data_model.router)
app.include_router(download.router)
app.include_router(entities.router)
app.include_router(analytics.router)
app.include_router(faults.router)
app.include_router(jobs_router.router)
app.include_router(bacnet.router)
app.include_router(run_fdd.router)
app.include_router(ws_router)

# Config UI (HA-style): HTML/CSS/JS in separate files, served at /app/
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount(
        "/app",
        StaticFiles(directory=str(_static_dir), html=True),
        name="config-ui",
    )


@app.get("/")
def root():
    """Root info for config UI: version, docs link, and BACnet URL from backend config."""
    return {
        "message": "Open-FDD API",
        "version": _app_version(),
        "docs": "/docs",
        "config_ui": "/app/",
        "bacnet_server_url": getattr(settings, "bacnet_server_url", None) or None,
    }


@app.get("/health")
def health():
    from open_fdd.platform.graph_model import get_serialization_status

    out = {"status": "ok"}
    out.update(get_serialization_status())
    return out


@app.get(
    "/capabilities",
    response_model=CapabilityResponse,
    summary="API version and feature flags (HA/Node-RED discovery)",
)
def capabilities():
    """
    Return version and feature flags. Use for discovery and to decide whether to
    use WebSocket (/ws/events), fault state (/faults/active), jobs (/jobs/*), or BACnet write.
    """
    return CapabilityResponse(
        version=_app_version(),
        features={
            "websocket": True,
            "fault_state": True,
            "jobs": True,
            "bacnet_write": True,
        },
    )


@app.post(
    "/bacnet-test",
    summary="Test BACnet server connection (for config UI)",
    deprecated=True,
)
def bacnet_test(body: dict = Body(...)):
    """Legacy: use POST /bacnet/server_hello instead. Server-side test of diy-bacnet-server."""
    result = bacnet.bacnet_server_hello(body)
    return result
