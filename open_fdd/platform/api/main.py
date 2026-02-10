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
