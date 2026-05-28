from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .paths import data_dir, static_dashboard_dir
from .routes import (
    agent_routes,
    auth_routes,
    bacnet_routes,
    health,
    playground_routes,
    rules_routes,
    sites_routes,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open-FDD Operator Bridge",
        description="Local REST bridge: pandas playground, RuleRunner, BACnet ingest, agent context.",
        version="0.1.0",
    )

    allow_lan = os.environ.get("OFDD_CORS_ALLOW_PRIVATE_LAN", "").strip() in {"1", "true", "yes"}
    origins = ["http://127.0.0.1:5173", "http://localhost:5173"]
    if allow_lan:
        origins.append("*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth_routes.router)
    app.include_router(playground_routes.router)
    app.include_router(rules_routes.router)
    app.include_router(sites_routes.router)
    app.include_router(bacnet_routes.router)
    app.include_router(agent_routes.router)

    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "rules").mkdir(parents=True, exist_ok=True)
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
            candidate = static_dir / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
