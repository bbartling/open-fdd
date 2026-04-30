from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import urllib.parse
from typing import Any, Literal
import logging
import os
import ctypes
import warnings

import pandas as pd
from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched
from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.time_utils import infer_timestamp_column
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.paths import default_rules_root
from open_fdd.gateway import codex_device_login

_log = logging.getLogger(__name__)


def _plot_frame_records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return rows as plain Python JSON types (numpy/pandas scalars break FastAPI JSON encode)."""
    if frame.empty:
        return []
    try:
        blob = frame.to_json(orient="records", date_format="iso", double_precision=15)
    except (TypeError, ValueError):
        work = frame.astype(object).where(pd.notnull(frame), None)
        blob = work.to_json(orient="records", date_format="iso", double_precision=15)
    return json.loads(blob) if blob else []


@dataclass
class BridgeServices:
    model: ModelService
    ingest: IngestService
    ttl: TtlService


def _build_services() -> BridgeServices:
    model = ModelService()
    ingest = IngestService(model_service=model)
    ttl = TtlService(model_store=model.store)
    return BridgeServices(model=model, ingest=ingest, ttl=ttl)


class CsvIngestBody(BaseModel):
    site_id: str
    source: str = "csv"
    csv_path: str


class ModelImportBody(BaseModel):
    payload: "ModelPayload"
    replace: bool = True


class RuleRunBody(BaseModel):
    site_id: str
    source: str = "csv"
    rules_path: str
    chunk_rows: int = 0
    start_ts: str | None = None
    end_ts: str | None = None
    target_memory_fraction: float = 0.25
    #: When set (non-empty), load and merge these driver sources on ``timestamp`` instead
    #: of using ``source`` alone. Tags match ingest storage (e.g. ``csv``, ``weather``,
    #: ``onboard``, ``bacnet``, or any future driver ``source`` string).
    sources: list[str] | None = None
    join_how: Literal["inner", "left", "outer", "right"] = "outer"


class SiteRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str = "Site"
    metadata: dict[str, Any] | None = None


class EquipmentRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    site_id: str | None = None
    name: str = "Equipment"
    equipment_type: str = "Equipment"
    metadata: dict[str, Any] | None = None


class PointRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    site_id: str | None = None
    equipment_id: str | None = None
    external_id: str | None = None
    brick_type: str | None = None
    fdd_input: str | None = None
    unit: str | None = None
    metadata: dict[str, Any] | None = None


class ModelPayload(BaseModel):
    sites: list[SiteRecord] = Field(default_factory=list)
    equipment: list[EquipmentRecord] = Field(default_factory=list)
    points: list[PointRecord] = Field(default_factory=list)


class ModelValidateBody(BaseModel):
    payload: ModelPayload


class WeatherIngestBody(BaseModel):
    site_id: str
    days_back: int = 1


class OnboardIngestBody(BaseModel):
    site_id: str


class BacnetIngestBody(BaseModel):
    site_id: str
    server_url: str | None = None
    api_key: str | None = None


class MlTrainBody(BaseModel):
    site_id: str
    source: str = "csv"
    target_col: str
    feature_cols: list[str] | None = None
    lag_cols: list[str] | None = None
    residual_quantile: float = 0.95
    rule_flag_col: str | None = None
    output_source: str | None = None


class TimeseriesQueryBody(BaseModel):
    site_id: str
    sources: list[str]
    start_ts: str | None = None
    end_ts: str | None = None
    columns: list[str] | None = None
    join_on_timestamp: bool = True
    join_how: Literal["inner", "left", "outer"] = "outer"
    limit: int = 10000


class TimeseriesBoundsBody(BaseModel):
    site_id: str
    source: str


class WeatherConfigBody(BaseModel):
    latitude: float
    longitude: float
    timezone: str = "UTC"
    base_url: str = "https://archive-api.open-meteo.com/v1/archive"


class BacnetConfigBody(BaseModel):
    enabled: bool = False
    interval_seconds: int = 300
    site_id: str | None = None
    server_url: str | None = None
    api_key: str | None = None


class OnboardConfigBody(BaseModel):
    base_url: str = "https://api.onboarddata.io"
    building_ids: str = ""
    lookback_hours: int = 24
    api_key: str | None = None
    allow_synthetic: bool = False


class DriversValidateBundle(BaseModel):
    """Draft driver configs for AI-assisted setup (validated without applying)."""

    model_config = ConfigDict(extra="ignore")
    weather: dict[str, Any] | None = None
    onboard: dict[str, Any] | None = None
    bacnet: dict[str, Any] | None = None


class SiteCreateBody(BaseModel):
    name: str


class SparqlQueryBody(BaseModel):
    query: str


class SparqlTextBody(BaseModel):
    query: str


class SiteRulePackBody(BaseModel):
    rule_pack: str


class CodexDevicePollBody(BaseModel):
    session_id: str


class TimeseriesPurgeBody(BaseModel):
    source: str | None = None
    site_id: str | None = None
    prune_points: bool = False


class RuleUploadBody(BaseModel):
    filename: str
    content: str


def _driver_health_entry(*, last_run: str = "", rows: int = 0, success: bool | None = None, last_error: str = "") -> dict[str, Any]:
    return {
        "last_run": last_run,
        "rows": int(rows),
        "success": success,
        "last_error": last_error,
    }


def _driver_health_update(status_map: dict[str, dict[str, Any]], *, driver: str, rows: int = 0, success: bool | None = None, error: str = "") -> None:
    status_map[driver] = _driver_health_entry(
        last_run=datetime.now(timezone.utc).isoformat(),
        rows=int(rows),
        success=success,
        last_error=str(error or ""),
    )


def create_app() -> FastAPI:
    services = _build_services()

    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI):
        task_ttl = asyncio.create_task(_ttl_sync_loop(app))
        task_bacnet = asyncio.create_task(_bacnet_poll_loop(app))
        app.state.ttl_sync_task = task_ttl
        app.state.bacnet_poll_task = task_bacnet
        try:
            yield
        finally:
            task_ttl.cancel()
            task_bacnet.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task_ttl
            with contextlib.suppress(asyncio.CancelledError):
                await task_bacnet

    app = FastAPI(
        title="open-fdd desktop bridge",
        description=(
            "Local desktop bridge API for model management, ingestion (CSV/weather/onboard/BACnet), "
            "timeseries joins, rules backfill, and Plotly-friendly views."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "health", "description": "Bridge health and readiness."},
            {"name": "sites", "description": "Site lifecycle and site-level rule pack config."},
            {"name": "model", "description": "Desktop model export/import/validate and TTL controls."},
            {"name": "ingest", "description": "CSV, weather, onboard, BACnet ingestion endpoints."},
            {"name": "timeseries", "description": "Feather-backed query, bounds, plots, and purge endpoints."},
            {"name": "rules", "description": "Rule execution, rule file management, and defaults."},
            {"name": "config", "description": "Weather, BACnet, and Onboard runtime configuration."},
            {"name": "sparql", "description": "SPARQL query endpoints for desktop TTL graph."},
            {"name": "system", "description": "Resource and storage stats."},
        ],
        lifespan=_lifespan,
    )
    _ui_port_raw = (os.environ.get("OFDD_UI_PORT") or "8080").strip() or "8080"
    try:
        _ui_port = int(_ui_port_raw)
        if not (1 <= _ui_port <= 65535):
            raise ValueError
    except ValueError:
        _ui_port = 8080
        _log.warning("Invalid OFDD_UI_PORT=%r; using 8080 for CORS static UI origins", _ui_port_raw)
    _static_ui_origins = (
        f"http://127.0.0.1:{_ui_port}",
        f"http://localhost:{_ui_port}",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            *_static_ui_origins,
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    def _rules_dir() -> Path:
        path = default_rules_root() / "ahu_vav"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_rule_filename(filename: str) -> str:
        name = Path(filename).name
        if name != filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        lower = name.lower()
        if not (lower.endswith(".yaml") or lower.endswith(".yml")):
            raise HTTPException(status_code=400, detail="Rule file must end with .yaml or .yml")
        return name

    def _safe_rules_path(raw_path: str) -> str:
        candidate = str(raw_path or "").strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="rules_path is required")
        rules_root = _rules_dir().resolve()
        if candidate in {".", "./"}:
            return str(rules_root)
        direct_file = rules_root / _safe_rule_filename(candidate)
        if direct_file.exists() and direct_file.is_file():
            return str(direct_file)
        try:
            candidate_path = Path(candidate).expanduser()
            if not candidate_path.is_absolute():
                candidate_path = (rules_root / candidate_path).resolve()
            else:
                candidate_path = candidate_path.resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid rules_path: {candidate}") from exc
        if rules_root == candidate_path or rules_root in candidate_path.parents:
            return str(candidate_path)
        raise HTTPException(status_code=400, detail="rules_path must be inside managed rules directory")
    def _safe_sync_ttl() -> str | None:
        try:
            services.ttl.sync()
            return None
        except Exception as exc:  # noqa: BLE001
            _log.exception("TTL sync failed")
            return str(exc)

    def _memory_info() -> dict[str, int | float]:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = int(stat.ullTotalPhys)
            avail = int(stat.ullAvailPhys)
        else:
            try:
                pages = int(os.sysconf("SC_PHYS_PAGES"))
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                try:
                    avail_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
                except (ValueError, OSError, KeyError):
                    # Darwin can omit SC_AVPHYS_PAGES; use total pages as conservative fallback.
                    avail_pages = pages
                total = pages * page_size
                avail = avail_pages * page_size
            except (ValueError, OSError, KeyError):
                total = 0
                avail = 0
        used = max(0, total - avail)
        pct = round((used / total) * 100, 2) if total > 0 else 0.0
        return {
            "total_bytes": total,
            "available_bytes": avail,
            "used_bytes": used,
            "used_percent": pct,
        }

    def _disk_info() -> dict[str, int | float | str]:
        target = Path.home()
        usage = shutil.disk_usage(target)
        total = int(usage.total)
        free = int(usage.free)
        used = int(usage.used)
        pct = round((used / total) * 100, 2) if total > 0 else 0.0
        return {
            "path": str(target),
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": used,
            "used_percent": pct,
        }

    raw_ttl_interval = os.getenv("OFDD_TTL_SYNC_INTERVAL_SECONDS", "30")
    try:
        ttl_interval = int(raw_ttl_interval or "30")
    except (TypeError, ValueError):
        ttl_interval = 30
    app.state.ttl_sync_interval_seconds = max(1, ttl_interval)
    app.state.last_ttl_sync_iso = ""
    app.state.ttl_sync_error = ""
    app.state.bacnet_poll_enabled = os.getenv("OFDD_BACNET_POLL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    raw_bacnet_interval = os.getenv("OFDD_BACNET_POLL_INTERVAL_SECONDS", "300")
    try:
        bacnet_interval = int(raw_bacnet_interval or "300")
    except (TypeError, ValueError):
        bacnet_interval = 300
    app.state.bacnet_poll_interval_seconds = max(
        5,
        bacnet_interval,
    )
    app.state.bacnet_site_id = (os.getenv("OFDD_BACNET_SITE_ID", "") or "").strip()
    app.state.bacnet_server_url = (os.getenv("OFDD_BACNET_SERVER_URL", "") or "").strip()
    app.state.bacnet_api_key = (os.getenv("OFDD_BACNET_SERVER_API_KEY", "") or "").strip()
    app.state.last_bacnet_poll = {}
    app.state.bacnet_poll_error = ""
    app.state.driver_health = {
        "csv": _driver_health_entry(),
        "weather": _driver_health_entry(),
        "bacnet": _driver_health_entry(),
        "onboard": _driver_health_entry(),
    }

    async def _ttl_sync_loop(app_ref: FastAPI) -> None:
        while True:
            try:
                path = await asyncio.to_thread(services.ttl.sync)
                app_ref.state.last_ttl_sync_iso = str(path)
                app_ref.state.ttl_sync_error = ""
            except Exception as exc:  # pragma: no cover - defensive runtime loop
                app_ref.state.ttl_sync_error = str(exc)
            await asyncio.sleep(int(app_ref.state.ttl_sync_interval_seconds))

    async def _bacnet_poll_loop(app_ref: FastAPI) -> None:
        while True:
            interval = max(5, int(app_ref.state.bacnet_poll_interval_seconds or 300))
            try:
                if bool(app_ref.state.bacnet_poll_enabled):
                    site_id = str(app_ref.state.bacnet_site_id or "").strip()
                    if not site_id:
                        model_sites = services.model.load().get("sites", [])
                        site_id = str(model_sites[0].get("id")) if model_sites else ""
                    if not site_id:
                        poll_msg = "BACnet polling enabled but no site is configured."
                        app_ref.state.bacnet_poll_error = poll_msg
                        _driver_health_update(
                            app_ref.state.driver_health,
                            driver="bacnet",
                            rows=0,
                            success=False,
                            error=poll_msg,
                        )
                    else:
                        result = await asyncio.to_thread(
                            services.ingest.ingest_bacnet,
                            site_id=site_id,
                            server_url=str(app_ref.state.bacnet_server_url or "").strip(),
                            api_key=str(app_ref.state.bacnet_api_key or "").strip(),
                        )
                        app_ref.state.last_bacnet_poll = result
                        if result.get("success", False):
                            app_ref.state.bacnet_poll_error = ""
                            _driver_health_update(
                                app_ref.state.driver_health,
                                driver="bacnet",
                                rows=int(result.get("rows", 0) or 0),
                                success=True,
                                error="",
                            )
                        else:
                            poll_error = str(result.get("error") or "BACnet polling failed.")
                            app_ref.state.bacnet_poll_error = poll_error
                            _driver_health_update(
                                app_ref.state.driver_health,
                                driver="bacnet",
                                rows=int(result.get("rows", 0) or 0),
                                success=False,
                                error=poll_error,
                            )
            except Exception as exc:  # pragma: no cover - defensive runtime loop
                loop_error = str(exc)
                app_ref.state.bacnet_poll_error = loop_error
                _driver_health_update(
                    app_ref.state.driver_health,
                    driver="bacnet",
                    rows=0,
                    success=False,
                    error=loop_error,
                )
            await asyncio.sleep(interval)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/openfdd-claw/codex/device/start", tags=["openfdd-claw"])
    def codex_device_start() -> dict[str, Any]:
        try:
            return codex_device_login.start_device_login()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/openfdd-claw/codex/device/poll", tags=["openfdd-claw"])
    def codex_device_poll(body: CodexDevicePollBody) -> dict[str, Any]:
        return codex_device_login.poll_device_login(body.session_id.strip())

    @app.get("/model/export", tags=["model"])
    def model_export() -> dict[str, Any]:
        return services.model.load()

    @app.get("/sites", tags=["sites"])
    def list_sites() -> list[dict[str, Any]]:
        return services.model.load().get("sites", [])

    @app.post("/sites", tags=["sites"])
    def create_site(body: SiteCreateBody) -> dict[str, Any]:
        site = services.model.create_site(body.name.strip() or "Site")
        ttl_error = _safe_sync_ttl()
        if ttl_error:
            site = {**site, "warning": f"TTL sync failed: {ttl_error}"}
        return site

    @app.delete("/sites/{site_id}", tags=["sites"])
    def delete_site(site_id: str) -> dict[str, Any]:
        out = services.model.delete_site(site_id)
        ttl_error = _safe_sync_ttl()
        if ttl_error:
            return {**out, "ttl_sync_warning": ttl_error}
        return out

    @app.post("/sites/{site_id}/rule-pack", tags=["sites"])
    def set_site_rule_pack(site_id: str, body: SiteRulePackBody) -> dict[str, Any]:
        with services.model.transaction() as model:
            site = next((s for s in model.get("sites", []) if str(s.get("id")) == str(site_id)), None)
            if site is None:
                raise HTTPException(status_code=404, detail=f"Unknown site id: {site_id}")
            metadata = site.get("metadata") if isinstance(site.get("metadata"), dict) else {}
            metadata["rule_pack"] = body.rule_pack
            site["metadata"] = metadata
        ttl_error = _safe_sync_ttl()
        if ttl_error:
            site = {**site, "warning": f"TTL sync failed: {ttl_error}"}
        return site

    @app.post("/model/import", tags=["model"])
    def model_import(body: ModelImportBody) -> dict[str, int]:
        payload = body.payload.model_dump(mode="python")
        normalized = {
            "sites": payload.get("sites", []) if isinstance(payload.get("sites"), list) else [],
            "equipment": payload.get("equipment", []) if isinstance(payload.get("equipment"), list) else [],
            "points": payload.get("points", []) if isinstance(payload.get("points"), list) else [],
        }
        with services.model.transaction() as model:
            if body.replace:
                model["sites"] = normalized["sites"]
                model["equipment"] = normalized["equipment"]
                model["points"] = normalized["points"]
            else:
                model["sites"].extend(normalized["sites"])
                model["equipment"].extend(normalized["equipment"])
                model["points"].extend(normalized["points"])
        return {
            "sites": len(normalized["sites"]),
            "equipment": len(normalized["equipment"]),
            "points": len(normalized["points"]),
        }

    @app.post("/model/validate", tags=["model"])
    def model_validate(body: ModelValidateBody) -> dict[str, Any]:
        payload = body.payload.model_dump(mode="python")
        sites = payload.get("sites", []) if isinstance(payload.get("sites"), list) else []
        equipment = payload.get("equipment", []) if isinstance(payload.get("equipment"), list) else []
        points = payload.get("points", []) if isinstance(payload.get("points"), list) else []
        issues: list[str] = []
        site_ids = {str(s.get("id")) for s in sites if s.get("id")}
        equipment_ids = {str(e.get("id")) for e in equipment if e.get("id")}
        for idx, e in enumerate(equipment):
            sid = e.get("site_id")
            if sid and str(sid) not in site_ids:
                issues.append(f"equipment[{idx}] references missing site_id={sid}")
        for idx, p in enumerate(points):
            sid = p.get("site_id")
            if sid and str(sid) not in site_ids:
                issues.append(f"points[{idx}] references missing site_id={sid}")
            eqid = p.get("equipment_id")
            if eqid and str(eqid) not in equipment_ids:
                issues.append(f"points[{idx}] references missing equipment_id={eqid}")
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "counts": {
                "sites": len(sites),
                "equipment": len(equipment),
                "points": len(points),
            },
        }

    @app.post("/model/ttl/sync", tags=["model"])
    def model_ttl_sync() -> dict[str, str]:
        path = services.ttl.sync()
        return {"path": str(path)}

    @app.get("/model/ttl/status", tags=["model"])
    def model_ttl_status() -> dict[str, Any]:
        return {
            "ttl_path": str(services.ttl.ttl_path),
            "ttl_mirror_path": str(services.ttl.ttl_mirror_path) if services.ttl.ttl_mirror_path else "",
            "sync_interval_seconds": int(app.state.ttl_sync_interval_seconds),
            "last_sync_path": app.state.last_ttl_sync_iso,
            "last_sync_error": app.state.ttl_sync_error,
        }

    @app.post("/ingest/csv", tags=["ingest"])
    def ingest_csv(body: CsvIngestBody) -> dict[str, Any]:
        csv_path = Path(body.csv_path).expanduser()
        if not csv_path.is_absolute():
            csv_path = (Path.cwd() / csv_path).resolve()
        if not csv_path.exists():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"CSV file not found: {body.csv_path}. "
                    f"Resolved path: {csv_path}. "
                    "Use an absolute file path (example: C:/Users/ben/Documents/data.csv)."
                ),
            )
        try:
            out = services.ingest.ingest_csv(csv_path=csv_path, site_id=body.site_id, source=body.source)
            _driver_health_update(
                app.state.driver_health,
                driver="csv",
                rows=int(out.get("rows", 0) or 0),
                success=True,
                error="",
            )
            return out
        except FileNotFoundError as exc:
            _driver_health_update(app.state.driver_health, driver="csv", rows=0, success=False, error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            _driver_health_update(app.state.driver_health, driver="csv", rows=0, success=False, error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ingest/csv/upload", tags=["ingest"])
    async def ingest_csv_upload(
        site_id: str = Form(...),
        source: str = Form("csv"),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        chunk_size = 64 * 1024
        suffix = Path(file.filename or "").suffix or ".csv"
        fd, tmp_name = tempfile.mkstemp(prefix="openfdd_upload_", suffix=suffix)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, mode="wb") as handle:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            out = services.ingest.ingest_csv(csv_path=tmp_path, site_id=site_id, source=source)
            _driver_health_update(
                app.state.driver_health,
                driver="csv",
                rows=int(out.get("rows", 0) or 0),
                success=True,
                error="",
            )
            return out
        except ValueError as exc:
            _driver_health_update(app.state.driver_health, driver="csv", rows=0, success=False, error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)

    @app.post("/rules/run", tags=["rules"])
    def rules_run(body: RuleRunBody) -> dict[str, Any]:
        merge_sources = [str(s).strip() for s in (body.sources or []) if str(s).strip()]
        try:
            if merge_sources:
                frame, merge_used = services.ingest.load_merged_sources_frame_window(
                    site_id=body.site_id,
                    sources=merge_sources,
                    start_ts=body.start_ts,
                    end_ts=body.end_ts,
                    join_how=str(body.join_how),
                )
                load_meta: dict[str, Any] = {
                    "load_mode": "merged",
                    "sources": merge_used,
                    "join_how": body.join_how,
                }
            else:
                frame = services.ingest.load_source_frame_window(
                    source=body.source,
                    site_id=body.site_id,
                    start_ts=body.start_ts,
                    end_ts=body.end_ts,
                )
                load_meta = {"load_mode": "single", "source": body.source}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if frame.empty:
            return {
                "input_rows": 0,
                "output_rows": 0,
                "columns": [],
                "fault_totals": {},
                "preview": "",
                **load_meta,
            }
        try:
            safe_rules_path = _safe_rules_path(body.rules_path)
            out = run_rule_loop_batched(
                frame,
                RuleLoopConfig(
                    rules_path=safe_rules_path,
                    chunk_rows=int(body.chunk_rows or 0),
                    target_memory_fraction=float(body.target_memory_fraction or 0.25),
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{exc}. Hint: this usually means a rule references a sensor column not present "
                    "in the selected source/window; try source='all' (joined) or map/upload matching points."
                ),
            ) from exc
        fault_cols = [
            c
            for c in out.columns
            if c.endswith("_flag") or c.endswith("_fault")
        ]
        fault_totals = {c: int(pd.to_numeric(out[c], errors="coerce").fillna(0).sum()) for c in fault_cols}
        preview = out.tail(10).to_string(index=False)
        return {
            "input_rows": len(frame.index),
            "output_rows": len(out.index),
            "columns": [str(c) for c in out.columns],
            "fault_totals": fault_totals,
            "preview": preview,
            **load_meta,
        }

    @app.post("/ingest/weather", tags=["ingest"])
    def ingest_weather(body: WeatherIngestBody) -> dict[str, Any]:
        out = services.ingest.ingest_weather(site_id=body.site_id, days_back=max(1, int(body.days_back)))
        _driver_health_update(
            app.state.driver_health,
            driver="weather",
            rows=int(out.get("rows", 0) or 0),
            success=True,
            error="",
        )
        return out

    @app.post("/ingest/onboard", tags=["ingest"])
    def ingest_onboard(body: OnboardIngestBody) -> dict[str, Any]:
        out = services.ingest.ingest_onboard(site_id=body.site_id)
        ok = bool(out.get("success", False))
        _driver_health_update(
            app.state.driver_health,
            driver="onboard",
            rows=int(out.get("rows", 0) or 0),
            success=ok,
            error=str(out.get("error") or ""),
        )
        return out

    @app.post("/ingest/bacnet", tags=["ingest"])
    def ingest_bacnet(body: BacnetIngestBody) -> dict[str, Any]:
        explicit_server_url = str(body.server_url or "").strip()
        server_url = explicit_server_url or str(app.state.bacnet_server_url or "").strip()
        if not server_url:
            raise HTTPException(
                status_code=400,
                detail="Missing BACnet server URL. Set /config/bacnet.server_url or pass server_url in request.",
            )
        if explicit_server_url:
            api_key = str(body.api_key or "").strip()
        else:
            api_key = str(body.api_key or app.state.bacnet_api_key or "").strip()
        result = services.ingest.ingest_bacnet(
            site_id=body.site_id,
            server_url=server_url,
            api_key=api_key,
        )
        app.state.last_bacnet_poll = result
        if not result.get("success", False):
            bacnet_error = str(result.get("error") or "BACnet ingest failed.")
            app.state.bacnet_poll_error = bacnet_error
            _driver_health_update(
                app.state.driver_health,
                driver="bacnet",
                rows=int(result.get("rows", 0) or 0),
                success=False,
                error=bacnet_error,
            )
        else:
            app.state.bacnet_poll_error = ""
            _driver_health_update(
                app.state.driver_health,
                driver="bacnet",
                rows=int(result.get("rows", 0) or 0),
                success=True,
                error="",
            )
        return result

    @app.post("/ml/train", tags=["ingest"])
    def ml_train(body: MlTrainBody) -> dict[str, Any]:
        return services.ingest.train_ml_baseline(
            site_id=body.site_id,
            source=body.source,
            target_col=body.target_col,
            feature_cols=body.feature_cols,
            lag_cols=body.lag_cols,
            residual_quantile=float(body.residual_quantile),
            rule_flag_col=body.rule_flag_col,
            output_source=body.output_source,
        )

    @app.post("/timeseries/query", tags=["timeseries"])
    def timeseries_query(body: TimeseriesQueryBody) -> dict[str, Any]:
        sources = [str(s).strip() for s in body.sources if str(s).strip()]
        if not sources:
            raise HTTPException(status_code=400, detail="Provide at least one source.")
        cap = max(1, min(int(body.limit), 50_000))
        frames: list[tuple[str, Any]] = []
        for src in sources:
            try:
                frame = services.ingest.load_source_frame_window(
                    source=src,
                    site_id=body.site_id,
                    start_ts=body.start_ts,
                    end_ts=body.end_ts,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if frame.empty:
                continue
            ts_col = infer_timestamp_column(frame)
            frame[ts_col] = frame[ts_col].astype(str)
            want_cols = [c for c in (body.columns or []) if c in frame.columns and c != ts_col]
            if want_cols:
                frame = frame[[ts_col, *want_cols]]
            frame = frame.tail(cap).copy()
            frames.append((src, frame))
        if not frames:
            return {"columns": [], "rows": []}

        if len(frames) == 1 or not body.join_on_timestamp:
            out_rows: list[dict[str, Any]] = []
            for src, frm in frames:
                copy = frm.copy().where(pd.notnull(frm), None)
                copy["source"] = src
                out_rows.extend(copy.to_dict(orient="records"))
            out = out_rows[-cap:]
            cols = list(out[0].keys()) if out else []
            return {"columns": cols, "rows": out}

        join_how = str(body.join_how)
        base_src, merged = frames[0]
        ts_col = infer_timestamp_column(merged)
        rename = {c: f"{c}_{base_src}" for c in merged.columns if c != ts_col}
        merged = merged.rename(columns=rename)
        for src, frm in frames[1:]:
            rhs = frm.copy()
            rhs_ts = infer_timestamp_column(rhs)
            if rhs_ts != ts_col:
                rhs = rhs.rename(columns={rhs_ts: ts_col})
            rhs = rhs.rename(columns={c: f"{c}_{src}" for c in rhs.columns if c != ts_col})
            merged = merged.merge(rhs, on=ts_col, how=join_how)
        merged = merged.tail(cap)
        merged = merged.where(pd.notnull(merged), None)
        return {"columns": [str(c) for c in merged.columns], "rows": merged.to_dict(orient="records")}

    @app.post("/timeseries/bounds", tags=["timeseries"])
    def timeseries_bounds(body: TimeseriesBoundsBody) -> dict[str, Any]:
        return services.ingest.source_time_bounds(source=body.source, site_id=body.site_id)

    @app.get("/config/weather", tags=["config"])
    def weather_config_get() -> dict[str, Any]:
        return {
            "latitude": os.getenv("OFDD_OPEN_METEO_LATITUDE", ""),
            "longitude": os.getenv("OFDD_OPEN_METEO_LONGITUDE", ""),
            "timezone": os.getenv("OFDD_OPEN_METEO_TIMEZONE", "UTC"),
            "base_url": os.getenv("OFDD_OPEN_METEO_BASE_URL", "https://archive-api.open-meteo.com/v1/archive"),
        }

    @app.post("/config/weather", tags=["config"])
    def weather_config_set(body: WeatherConfigBody) -> dict[str, Any]:
        os.environ["OFDD_OPEN_METEO_LATITUDE"] = str(body.latitude)
        os.environ["OFDD_OPEN_METEO_LONGITUDE"] = str(body.longitude)
        os.environ["OFDD_OPEN_METEO_TIMEZONE"] = str(body.timezone or "UTC")
        os.environ["OFDD_OPEN_METEO_BASE_URL"] = str(body.base_url or "https://archive-api.open-meteo.com/v1/archive")
        return weather_config_get()

    @app.get("/config/bacnet", tags=["config"])
    def bacnet_config_get() -> dict[str, Any]:
        return {
            "enabled": bool(app.state.bacnet_poll_enabled),
            "interval_seconds": int(app.state.bacnet_poll_interval_seconds),
            "site_id": str(app.state.bacnet_site_id or ""),
            "server_url": str(app.state.bacnet_server_url or ""),
            "api_key_set": bool(str(app.state.bacnet_api_key or "").strip()),
            "last_poll": app.state.last_bacnet_poll,
            "last_error": str(app.state.bacnet_poll_error or ""),
        }

    @app.post("/config/bacnet", tags=["config"])
    def bacnet_config_set(body: BacnetConfigBody) -> dict[str, Any]:
        app.state.bacnet_poll_enabled = bool(body.enabled)
        app.state.bacnet_poll_interval_seconds = max(5, int(body.interval_seconds or 300))
        app.state.bacnet_site_id = str(body.site_id or "").strip()
        app.state.bacnet_server_url = str(body.server_url or "").strip()
        app.state.bacnet_api_key = str(body.api_key or "").strip()
        if app.state.bacnet_server_url:
            os.environ["OFDD_BACNET_SERVER_URL"] = str(app.state.bacnet_server_url)
        else:
            os.environ.pop("OFDD_BACNET_SERVER_URL", None)
        if app.state.bacnet_api_key:
            os.environ["OFDD_BACNET_SERVER_API_KEY"] = str(app.state.bacnet_api_key)
        else:
            os.environ.pop("OFDD_BACNET_SERVER_API_KEY", None)
        os.environ["OFDD_BACNET_POLL_INTERVAL_SECONDS"] = str(app.state.bacnet_poll_interval_seconds)
        os.environ["OFDD_BACNET_POLL_ENABLED"] = "true" if app.state.bacnet_poll_enabled else "false"
        if app.state.bacnet_site_id:
            os.environ["OFDD_BACNET_SITE_ID"] = str(app.state.bacnet_site_id)
        else:
            os.environ.pop("OFDD_BACNET_SITE_ID", None)
        return bacnet_config_get()

    @app.get("/config/drivers/health", tags=["config"])
    def drivers_health_get() -> dict[str, Any]:
        return dict(app.state.driver_health)

    @app.get("/config/drivers/export", tags=["config"])
    def drivers_export_get() -> dict[str, Any]:
        """
        Sanitized driver bundle for LLM-assisted setup (paste into chat, then
        ``POST /config/drivers/validate`` before applying ``POST /config/*``).
        """
        return {
            "schema_version": 1,
            "weather": weather_config_get(),
            "onboard": onboard_config_get(),
            "bacnet": bacnet_config_get(),
            "health": drivers_health_get(),
        }

    @app.post("/config/drivers/validate", tags=["config"])
    def drivers_validate_post(body: DriversValidateBundle) -> dict[str, Any]:
        errors: dict[str, Any] = {}
        warnings: list[str] = []

        if body.weather is not None:
            try:
                WeatherConfigBody.model_validate(body.weather)
            except ValidationError as exc:
                errors["weather"] = exc.errors()

        if body.onboard is not None:
            try:
                OnboardConfigBody.model_validate(body.onboard)
            except ValidationError as exc:
                errors["onboard"] = exc.errors()

        if body.bacnet is not None:
            try:
                BacnetConfigBody.model_validate(body.bacnet)
            except ValidationError as exc:
                errors["bacnet"] = exc.errors()
            else:
                url = str((body.bacnet or {}).get("server_url") or "")
                if "127.0.1:" in url:
                    warnings.append(
                        "bacnet.server_url looks like typo 127.0.1 — use 127.0.0.1 (four octets)."
                    )

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    @app.get("/config/onboard", tags=["config"])
    def onboard_config_get() -> dict[str, Any]:
        raw_lookback = os.getenv("OFDD_ONBOARD_LOOKBACK_HOURS", "24")
        try:
            lookback_hours = int(str(raw_lookback).strip() or "24")
        except (TypeError, ValueError):
            lookback_hours = 24
        lookback_hours = max(1, min(lookback_hours, 24 * 30))
        return {
            "base_url": os.getenv("OFDD_ONBOARD_API_BASE_URL", "https://api.onboarddata.io"),
            "building_ids": os.getenv("OFDD_ONBOARD_BUILDING_IDS", ""),
            "lookback_hours": lookback_hours,
            "api_key_set": bool(str(os.getenv("OFDD_ONBOARD_API_KEY", "")).strip()),
            "allow_synthetic": os.getenv("OFDD_ONBOARD_ALLOW_SYNTHETIC", "").strip().lower() in {"1", "true", "yes", "on"},
        }

    @app.post("/config/onboard", tags=["config"])
    def onboard_config_set(body: OnboardConfigBody) -> dict[str, Any]:
        os.environ["OFDD_ONBOARD_API_BASE_URL"] = str(body.base_url or "https://api.onboarddata.io").strip()
        os.environ["OFDD_ONBOARD_BUILDING_IDS"] = str(body.building_ids or "").strip()
        os.environ["OFDD_ONBOARD_LOOKBACK_HOURS"] = str(max(1, int(body.lookback_hours or 24)))
        os.environ["OFDD_ONBOARD_ALLOW_SYNTHETIC"] = "true" if bool(body.allow_synthetic) else "false"
        if body.api_key is not None:
            os.environ["OFDD_ONBOARD_API_KEY"] = str(body.api_key).strip()
        return onboard_config_get()

    @app.get("/plots/frame", tags=["timeseries"])
    def plots_frame(site_id: str, source: str = "csv", limit: int = 5000) -> dict[str, Any]:
        frame = services.ingest.load_source_frame(source=source, site_id=site_id)
        if frame.empty:
            return {"columns": [], "rows": []}
        cap = max(1, min(int(limit), 20_000))
        frame = frame.tail(cap).copy()
        frame = frame.where(pd.notnull(frame), None)
        if "timestamp" in frame.columns:
            frame["timestamp"] = frame["timestamp"].astype(str)
        return {
            "columns": [str(c) for c in frame.columns],
            "rows": _plot_frame_records_json_safe(frame),
        }

    @app.get("/plots/site-frame", tags=["timeseries"])
    def plots_site_frame(site_id: str, sources: str = "csv,weather,onboard,bacnet", limit: int = 5000) -> dict[str, Any]:
        cap = max(1, min(int(limit), 20_000))
        source_list = [s.strip() for s in str(sources).split(",") if s.strip()]
        if not source_list:
            source_list = ["csv"]
        merged, used_sources = services.ingest.load_merged_sources_frame_window(
            site_id=site_id,
            sources=source_list,
            start_ts=None,
            end_ts=None,
            join_how="outer",
        )
        if merged.empty:
            return {"columns": [], "rows": [], "sources": []}
        ts_col = infer_timestamp_column(merged)
        out = merged.tail(cap).copy()
        out = out.where(pd.notnull(out), None)
        if ts_col in out.columns:
            out[ts_col] = out[ts_col].astype(str)
        return {
            "columns": [str(c) for c in out.columns],
            "rows": _plot_frame_records_json_safe(out),
            "sources": used_sources,
        }

    @app.get("/data-model/testing/predefined", tags=["sparql"])
    def data_model_testing_predefined() -> list[dict[str, str]]:
        return [
            {
                "id": "sites",
                "label": "List sites",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label . }
}
ORDER BY ?site_label""",
            },
            {
                "id": "ahu_count",
                "label": "Count AHUs",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?ahu) AS ?count) WHERE {
  ?ahu a brick:Air_Handling_Unit .
}""",
            },
            {
                "id": "class_summary",
                "label": "Class summary",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?type (COUNT(?e) AS ?count) WHERE {
  ?e a ?type .
  FILTER(STRSTARTS(STR(?type), "https://brickschema.org/schema/Brick#"))
}
GROUP BY ?type
ORDER BY DESC(?count)
LIMIT 50""",
            },
            {
                "id": "vav_count",
                "label": "Count VAV boxes",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?vav) AS ?count) WHERE {
  ?vav a ?t .
  VALUES ?t { brick:Variable_Air_Volume_Box brick:Variable_Air_Volume_Box_With_Reheat }
}""",
            },
            {
                "id": "ahu_vav_system_counts",
                "label": "AHU + VAV system counts",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?system_type (COUNT(?e) AS ?count) WHERE {
  ?e a ?t .
  VALUES (?t ?system_type) {
    (brick:Air_Handling_Unit "AHU")
    (brick:Variable_Air_Volume_Box "VAV")
    (brick:Variable_Air_Volume_Box_With_Reheat "VAV_Reheat")
  }
}
GROUP BY ?system_type
ORDER BY ?system_type""",
            },
            {
                "id": "plant_equipment_counts",
                "label": "Central plant counts (chiller/boiler/tower)",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?plant_type (COUNT(?e) AS ?count) WHERE {
  ?e a ?t .
  VALUES (?t ?plant_type) {
    (brick:Chiller "Chiller")
    (brick:Boiler "Boiler")
    (brick:Cooling_Tower "Cooling_Tower")
  }
}
GROUP BY ?plant_type
ORDER BY ?plant_type""",
            },
            {
                "id": "water_cooled_chiller_plant_counts",
                "label": "Water-cooled chiller plant proxy counts",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?plant_component (COUNT(?e) AS ?count) WHERE {
  ?e a ?t .
  VALUES (?t ?plant_component) {
    (brick:Chiller "Chiller")
    (brick:Cooling_Tower "Cooling_Tower")
    (brick:Condenser_Water_Loop "Condenser_Water_Loop")
    (brick:Chilled_Water_Loop "Chilled_Water_Loop")
  }
}
GROUP BY ?plant_component
ORDER BY ?plant_component""",
            },
            {
                "id": "heat_pump_vrf_counts",
                "label": "Heat pump / VRF counts",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?equip_type (COUNT(?e) AS ?count) WHERE {
  ?e a ?t .
  VALUES (?t ?equip_type) {
    (brick:Heat_Pump "Heat_Pump")
    (brick:VRF "VRF")
    (brick:Variable_Refrigerant_Flow_Unit "Variable_Refrigerant_Flow_Unit")
  }
}
GROUP BY ?equip_type
ORDER BY ?equip_type""",
            },
            {
                "id": "feeds_relationships",
                "label": "feeds / isFedBy relationships",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?src ?rel ?dst WHERE {
  {
    ?src brick:feeds ?dst .
    BIND("feeds" AS ?rel)
  }
  UNION
  {
    ?src brick:isFedBy ?dst .
    BIND("isFedBy" AS ?rel)
  }
}
ORDER BY ?rel ?src ?dst
LIMIT 200""",
            },
            {
                "id": "ahu_setpoints",
                "label": "AHU SAT + duct pressure setpoints",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?ahu ?ahu_label ?sp ?sp_type WHERE {
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL { ?ahu <http://www.w3.org/2000/01/rdf-schema#label> ?ahu_label . }
  ?sp brick:isPointOf ?ahu .
  ?sp a ?sp_type .
  VALUES ?sp_type {
    brick:Supply_Air_Temperature_Setpoint
    brick:Supply_Air_Static_Pressure_Setpoint
  }
}
ORDER BY ?ahu ?sp_type""",
            },
            {
                "id": "chiller_leaving_temp",
                "label": "Chiller leaving temp sensors/setpoints",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?chiller ?point ?point_type WHERE {
  ?chiller a brick:Chiller .
  ?point brick:isPointOf ?chiller .
  ?point a ?point_type .
  VALUES ?point_type {
    brick:Chilled_Water_Supply_Temperature_Sensor
    brick:Chilled_Water_Supply_Temperature_Setpoint
    brick:Leaving_Chilled_Water_Temperature_Sensor
  }
}
ORDER BY ?chiller ?point_type""",
            },
            {
                "id": "dcv_co2_summary",
                "label": "DCV / CO2 sensor summary",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?co2_type (COUNT(?p) AS ?count) WHERE {
  ?p a ?co2_type .
  VALUES ?co2_type {
    brick:CO2_Sensor
    brick:CO2_Level_Sensor
    brick:Zone_Air_CO2_Sensor
    brick:Return_Air_CO2_Sensor
  }
}
GROUP BY ?co2_type
ORDER BY ?co2_type""",
            },
            {
                "id": "economizer_free_cooling_summary",
                "label": "Free cooling / economizer points",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?point_type (COUNT(?p) AS ?count) WHERE {
  ?p a ?point_type .
  VALUES ?point_type {
    brick:Economizer_Enable_Command
    brick:Economizer_Status
    brick:Outside_Air_Damper_Position_Command
    brick:Outside_Air_Damper_Position_Sensor
  }
}
GROUP BY ?point_type
ORDER BY ?point_type""",
            },
            {
                "id": "mechanical_system_summary",
                "label": "Mechanical system summary",
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?class (COUNT(?e) AS ?count) WHERE {
  ?e a ?class .
  VALUES ?class {
    brick:Air_Handling_Unit
    brick:Variable_Air_Volume_Box
    brick:Variable_Air_Volume_Box_With_Reheat
    brick:Heat_Pump
    brick:Chiller
    brick:Boiler
    brick:Cooling_Tower
  }
}
GROUP BY ?class
ORDER BY DESC(?count)""",
            },
        ]

    @app.get("/data-model/testing/health-summary", tags=["sparql"])
    def data_model_testing_health_summary() -> dict[str, Any]:
        model = services.model.load()
        sites = model.get("sites", []) if isinstance(model.get("sites"), list) else []
        equipment = model.get("equipment", []) if isinstance(model.get("equipment"), list) else []
        points = model.get("points", []) if isinstance(model.get("points"), list) else []

        site_ids = {str(s.get("id")) for s in sites if isinstance(s, dict) and s.get("id")}
        equipment_ids = {str(e.get("id")) for e in equipment if isinstance(e, dict) and e.get("id")}

        orphan_equipment = 0
        for eq in equipment:
            if not isinstance(eq, dict):
                continue
            sid = eq.get("site_id")
            if sid and str(sid) not in site_ids:
                orphan_equipment += 1

        orphan_points_site = 0
        orphan_points_equipment = 0
        missing_brick_type = 0
        missing_fdd_input = 0
        duplicate_map: dict[tuple[str, str, str], int] = {}
        for pt in points:
            if not isinstance(pt, dict):
                continue
            sid = pt.get("site_id")
            eqid = pt.get("equipment_id")
            if sid and str(sid) not in site_ids:
                orphan_points_site += 1
            if eqid and str(eqid) not in equipment_ids:
                orphan_points_equipment += 1
            if not str(pt.get("brick_type") or "").strip():
                missing_brick_type += 1
            if not str(pt.get("fdd_input") or "").strip():
                missing_fdd_input += 1
            key = (
                str(pt.get("site_id") or ""),
                str(pt.get("equipment_id") or ""),
                str(pt.get("external_id") or ""),
            )
            duplicate_map[key] = duplicate_map.get(key, 0) + 1
        duplicate_external_ids = sum(1 for count in duplicate_map.values() if count > 1)

        critical = orphan_equipment + orphan_points_site + orphan_points_equipment
        warning = missing_brick_type + missing_fdd_input + duplicate_external_ids
        score = max(0, 100 - (critical * 10) - (warning * 2))
        return {
            "score": score,
            "counts": {
                "sites": len(sites),
                "equipment": len(equipment),
                "points": len(points),
                "orphan_equipment": orphan_equipment,
                "orphan_points_site": orphan_points_site,
                "orphan_points_equipment": orphan_points_equipment,
                "missing_brick_type": missing_brick_type,
                "missing_fdd_input": missing_fdd_input,
                "duplicate_external_ids": duplicate_external_ids,
            },
            "summary": (
                f"Health score={score}; critical={critical}; warnings={warning}. "
                "Check orphan links, missing BRICK/FDD mappings, and duplicate external IDs."
            ),
        }

    @app.post("/data-model/testing/query", tags=["sparql"])
    def data_model_testing_query(body: SparqlQueryBody) -> dict[str, Any]:
        try:
            from rdflib import Graph
        except ImportError:
            return {"columns": [], "rows": [], "error": "rdflib not installed"}
        ttl_path = services.ttl.sync()
        graph = Graph()
        graph.parse(ttl_path, format="turtle")
        rows = []
        columns: list[str] = []
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="'count' is passed as positional argument",
                    category=DeprecationWarning,
                )
                query_rows = list(graph.query(body.query))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid SPARQL query: {exc}") from exc
        for row in query_rows:
            row_map = row.asdict() if hasattr(row, "asdict") else {}
            if not columns:
                columns = [str(k) for k in row_map.keys()]
            rows.append({k: str(v) for k, v in row_map.items()})
        return {"columns": columns, "rows": rows}

    @app.post("/data-model/sparql", tags=["sparql"])
    def data_model_sparql(body: SparqlTextBody) -> dict[str, Any]:
        """
        AFDD-stack style SPARQL endpoint for agent compatibility.
        Returns list of binding dictionaries under `bindings`.
        """
        result = data_model_testing_query(SparqlQueryBody(query=body.query))
        return {"bindings": result.get("rows", [])}

    @app.post("/data-model/sparql/upload", tags=["sparql"])
    async def data_model_sparql_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".sparql"):
            raise HTTPException(status_code=400, detail="Upload a .sparql file")
        try:
            query = (await file.read()).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Uploaded file must be UTF-8 encoded") from exc
        return data_model_sparql(SparqlTextBody(query=query))

    @app.get("/data-model/ttl", tags=["model"])
    def data_model_ttl(save: bool = False) -> Response:
        ttl = services.ttl.build_ttl()
        if save:
            services.ttl.sync()
        return Response(content=ttl, media_type="text/plain; charset=utf-8")

    @app.get("/rules/defaults", tags=["rules"])
    def list_default_rules() -> dict[str, Any]:
        source_dir = Path(__file__).resolve().parents[1] / "default_rules" / "ahu_vav"
        files = sorted(source_dir.glob("*.yaml"))
        return {
            "rule_pack": "ahu_vav",
            "source_dir": str(source_dir),
            "files": [f.name for f in files],
        }

    @app.post("/rules/defaults/install", tags=["rules"])
    def install_default_rules() -> dict[str, Any]:
        source_dir = Path(__file__).resolve().parents[1] / "default_rules" / "ahu_vav"
        dest_dir = default_rules_root() / "ahu_vav"
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for src in sorted(source_dir.glob("*.yaml")):
            dst = dest_dir / src.name
            shutil.copy2(src, dst)
            copied.append(src.name)
        return {"rule_pack": "ahu_vav", "rules_path": str(dest_dir), "copied": copied}

    @app.get("/rules", tags=["rules"])
    def list_rules() -> dict[str, Any]:
        rules_dir = _rules_dir()
        files = sorted(
            [p.name for p in rules_dir.iterdir() if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}]
        )
        return {"rules_dir": str(rules_dir), "files": files}

    @app.get("/rules/{filename}", tags=["rules"])
    def get_rule_file(filename: str) -> Response:
        safe = _safe_rule_filename(filename)
        path = _rules_dir() / safe
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"Rule file not found: {safe}")
        return Response(content=path.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")

    @app.post("/rules", tags=["rules"])
    def upload_rule_file(body: RuleUploadBody) -> dict[str, Any]:
        safe = _safe_rule_filename(body.filename.strip())
        path = _rules_dir() / safe
        path.write_text(body.content, encoding="utf-8")
        return {"filename": safe, "size": len(body.content)}

    @app.delete("/rules/{filename}", tags=["rules"])
    def delete_rule_file(filename: str) -> dict[str, str]:
        safe = _safe_rule_filename(filename)
        path = _rules_dir() / safe
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"Rule file not found: {safe}")
        path.unlink()
        return {"deleted": safe}

    @app.post("/rules/sync-definitions", tags=["rules"])
    def sync_rule_definitions() -> dict[str, Any]:
        # Desktop bridge does not persist separate DB fault definitions.
        # This endpoint mirrors AFDD frontend UX and is a no-op.
        return {"synced": 0, "mode": "desktop_noop"}

    @app.get("/storage/timeseries/stats", tags=["timeseries"])
    def timeseries_stats() -> dict[str, int]:
        return services.ingest.feather_store.stats()

    @app.get("/system/resources", tags=["system"])
    def system_resources() -> dict[str, Any]:
        return {
            "memory": _memory_info(),
            "disk": _disk_info(),
        }

    @app.post("/storage/timeseries/purge", tags=["timeseries"])
    def timeseries_purge(body: TimeseriesPurgeBody) -> dict[str, Any]:
        out = services.ingest.purge_timeseries(source=body.source, site_id=body.site_id)
        points_removed = 0
        ttl_error: str | None = None
        if body.prune_points:
            with services.model.transaction() as model:
                before = len(model.get("points", []))
                kept = []
                for point in model.get("points", []):
                    md = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
                    p_source = md.get("source")
                    p_site = point.get("site_id")
                    match_source = body.source is None or str(p_source) == str(body.source)
                    match_site = body.site_id is None or str(p_site) == str(body.site_id)
                    if match_source and match_site:
                        continue
                    kept.append(point)
                model["points"] = kept
            ttl_error = _safe_sync_ttl()
            points_removed = before - len(kept)
        if ttl_error:
            return {**out, "points_removed": points_removed, "ttl_sync_warning": ttl_error}
        return {**out, "points_removed": points_removed}

    return app


def run_gateway(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the ASGI server (requires ``pip install 'open-fdd[desktop]'``)."""
    from open_fdd.gateway.cli import run_gateway as _run

    _run(host=host, port=port)


run_desktop_bridge = run_gateway


if __name__ == "__main__":
    from open_fdd.gateway.cli import run_gateway as _run_main

    _run_main()
