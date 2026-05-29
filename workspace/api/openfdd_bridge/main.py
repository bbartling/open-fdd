from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .middleware import AuditMiddleware, global_exception_handler
from .paths import data_dir, static_dashboard_dir
from .routes import (
    agent_routes,
    audit_routes,
    auth_routes,
    bacnet_routes,
    building_routes,
    health,
    host_routes,
    model_routes,
    playground_routes,
    sites_routes,
)
from .settings import cors_allow_private_lan, cors_origins


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open-FDD Operator Bridge",
        description="Local REST bridge: Python Rule Lab, BRICK data model, BACnet ingest, agent context.",
        version="0.1.0",
    )

    allow_lan = cors_allow_private_lan()
    origins = cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(AuditMiddleware)

    app.include_router(health.router)
    app.include_router(auth_routes.router)
    app.include_router(audit_routes.router)
    app.include_router(playground_routes.router)
    app.include_router(model_routes.router)
    app.include_router(building_routes.router)
    app.include_router(sites_routes.router)
    app.include_router(bacnet_routes.router)
    app.include_router(agent_routes.router)
    app.include_router(host_routes.router)

    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "playground").mkdir(parents=True, exist_ok=True)

    static_dir = static_dashboard_dir()
    if static_dir.is_dir() and (static_dir / "index.html").is_file():

        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def spa_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith("api/") or full_path.startswith("openfdd-agent"):
                raise HTTPException(status_code=404)
            if ".." in Path(full_path).parts:
                raise HTTPException(status_code=404)
            static_resolved = static_dir.resolve(strict=False)
            candidate_resolved = (static_dir / full_path).resolve(strict=False)
            try:
                candidate_resolved.relative_to(static_resolved)
            except ValueError:
                raise HTTPException(status_code=404) from None
            if candidate_resolved.is_file():
                return FileResponse(candidate_resolved)
            return FileResponse(static_resolved / "index.html")

    app.add_exception_handler(Exception, global_exception_handler)

    return app


app = create_app()
