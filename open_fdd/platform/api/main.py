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
    points,
    equipment,
    rules as rules_router,
    run_fdd,
    sites,
    timeseries as timeseries_router,
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


_SWAGGER_DESCRIPTION = (
    "When the server has API key auth enabled (OFDD_API_KEY set), **Try it out** will return 401 until you authorize: "
    "click **Authorize** at the top, paste your API key (e.g. from `stack/.env` → `OFDD_API_KEY`), then click Authorize and Close. "
    "After that, all requests from Swagger include the Bearer token."
)

app = FastAPI(
    title=settings.app_title,
    version=_app_version(),
    description=_SWAGGER_DESCRIPTION,
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


def _custom_openapi():
    """Inject Bearer auth into OpenAPI so Swagger UI shows Authorize and sends the token with requests."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
    )
    schema["components"] = schema.get("components") or {}
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "When OFDD_API_KEY is set, use the value from stack/.env. In Swagger: click Authorize, paste the key, then Try it out.",
        }
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi

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
app.include_router(timeseries_router.router)
app.include_router(entities.router)
app.include_router(analytics.router)
app.include_router(faults.router)
app.include_router(rules_router.router)
app.include_router(jobs_router.router)
app.include_router(bacnet.router)
app.include_router(run_fdd.router)
app.include_router(ws_router)

# Legacy config UI at /app/ (optional; removed when using React frontend only)
_static_dir = Path(__file__).resolve().parent.parent / "static"
_has_static_ui = _static_dir.is_dir() and (_static_dir / "index.html").is_file()
if _has_static_ui:
    app.mount(
        "/app",
        StaticFiles(directory=str(_static_dir), html=True),
        name="config-ui",
    )


@app.get("/")
def root():
    """Root info: version, docs link, and BACnet URL from backend config."""
    out = {
        "message": "Open-FDD API",
        "version": _app_version(),
        "docs": "/docs",
        "bacnet_server_url": getattr(settings, "bacnet_server_url", None) or None,
    }
    if _has_static_ui:
        out["config_ui"] = "/app/"
    return out


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
