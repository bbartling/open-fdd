from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .middleware import AuditMiddleware, global_exception_handler
from .paths import data_dir, static_dashboard_dir
from .security import validate_startup_auth
from .security_headers import SecurityHeadersMiddleware
from .static_files import CachedStaticFiles
from .routes import (
    agent_routes,
    audit_routes,
    auth_routes,
    bacnet_routes,
    building_routes,
    faults_routes,
    health,
    host_routes,
    modbus_routes,
    model_routes,
    playground_routes,
    rules_routes,
    sites_routes,
    timeseries_routes,
)
from .settings import cors_allow_headers, cors_allow_methods, cors_origins


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from .bacnet_poll_worker import start_bacnet_poll_worker
    from .log_rotation import rotate_logs_on_startup

    rotate_logs_on_startup()
    start_bacnet_poll_worker()
    yield


def create_app() -> FastAPI:
    validate_startup_auth()
    app = FastAPI(
        title="Open-FDD Operator Bridge",
        description="Local REST bridge: Python Rule Lab, BRICK data model, BACnet ingest, agent context.",
        version="0.2.0",
        lifespan=_lifespan,
    )

    origins = cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=cors_allow_methods(),
        allow_headers=cors_allow_headers(),
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AuditMiddleware)

    app.include_router(health.router)
    app.include_router(auth_routes.router)
    app.include_router(audit_routes.router)
    app.include_router(playground_routes.router)
    app.include_router(rules_routes.router)
    app.include_router(model_routes.router)
    app.include_router(timeseries_routes.router)
    app.include_router(building_routes.router)
    app.include_router(faults_routes.router)
    app.include_router(sites_routes.router)
    app.include_router(bacnet_routes.router)
    app.include_router(modbus_routes.router)
    app.include_router(agent_routes.router)
    app.include_router(host_routes.router)

    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "playground").mkdir(parents=True, exist_ok=True)

    static_dir = static_dashboard_dir()
    if static_dir.is_dir() and (static_dir / "index.html").is_file():

        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", CachedStaticFiles(directory=assets), name="assets")

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


class _LazyASGI:
    """Defer ``create_app()`` (and startup auth checks) until first request — import-safe for tests."""

    def __init__(self) -> None:
        self._inner: FastAPI | None = None

    def _load(self) -> FastAPI:
        if self._inner is None:
            self._inner = create_app()
        return self._inner

    async def __call__(self, scope, receive, send):
        await self._load()(scope, receive, send)

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


# uvicorn openfdd_bridge.main:app
app = _LazyASGI()
