"""Open-FDD CRUD API — data model, sites, points, equipment."""

import importlib.metadata
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.api import (
    analytics,
    bacnet,
    data_model,
    download,
    sites,
    points,
    equipment,
    run_fdd,
)

settings = get_platform_settings()


def _app_version() -> str:
    """Open-FDD version from installed package; updates with pip install."""
    try:
        return importlib.metadata.version("open-fdd")
    except importlib.metadata.PackageNotFoundError:
        return getattr(settings, "app_version", "0.1.0")


app = FastAPI(
    title=settings.app_title,
    version=_app_version(),
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
            "description": "Proxy to diy-bacnet-server (server_hello, whois_range, point_discovery). Backend hits the gateway; use same host or OT LAN URL.",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites.router)
app.include_router(points.router)
app.include_router(equipment.router)
app.include_router(data_model.router)
app.include_router(download.router)
app.include_router(analytics.router)
app.include_router(bacnet.router)
app.include_router(run_fdd.router)

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
    return {"status": "ok"}


@app.post(
    "/bacnet-test",
    summary="Test BACnet server connection (for config UI)",
    deprecated=True,
)
def bacnet_test(body: dict = Body(...)):
    """Legacy: use POST /bacnet/server_hello instead. Server-side test of diy-bacnet-server."""
    result = bacnet.bacnet_server_hello(body)
    return result
