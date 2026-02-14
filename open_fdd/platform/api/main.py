"""Open-FDD CRUD API — data model, sites, points, equipment."""

import importlib.metadata

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.api import analytics, data_model, download, sites, points, equipment, run_fdd

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
app.include_router(run_fdd.router)


@app.get("/")
def root():
    return {"message": "Open-FDD API", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}
