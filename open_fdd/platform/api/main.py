"""Open-FDD CRUD API — data model, sites, points, equipment."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.api import data_model, sites, points, equipment

settings = get_platform_settings()
app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "data-model",
            "description": "**Brick data modeling workflow:** 1) Create site via POST /sites (required first). 2) GET /data-model/export — copy JSON (point_id, external_id, site_id). 3) Add brick_type, rule_input (= time-series ref, often external_id e.g. HTG-O), site_id, equipment_id per point. 4) PUT /data-model/import — send full payload. TTL auto-syncs to config/brick_model.ttl on every CRUD/import. 5) GET /data-model/ttl, POST /data-model/sparql — validate.",
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


@app.get("/")
def root():
    return {"message": "Open-FDD API", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}
