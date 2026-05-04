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
import platform
import time
import ctypes
import ctypes.util
import subprocess
import warnings

import pandas as pd
import yaml

from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import Response
from fastapi import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched
from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.time_utils import infer_timestamp_column
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.services.plot_readiness import TimeseriesPlotReadiness, analyze_dataframe_for_plot
from open_fdd.desktop.storage.paths import default_rules_root
from open_fdd.gateway import codex_device_login, local_codex_cli
from open_fdd.gateway.openfdd_agent import run_openfdd_agent_turn
from open_fdd.gateway.openfdd_agent_context import build_agent_bootstrap_context

_log = logging.getLogger(__name__)


def _allow_local_codex_install_cli() -> bool:
    raw = (os.environ.get("OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _normalize_rule_files_basenames(rule_files: list[str] | None) -> list[str] | None:
    """
    When ``rule_files`` is omitted or empty, return None (all YAML in the rules dir).
    When it is non-empty but every entry is filtered out (non-.yaml/.yml), raise 400.
    """
    if not rule_files:
        return None
    seen: list[str] = []
    for raw in rule_files:
        base = Path(str(raw or "").strip()).name
        if not base.lower().endswith((".yaml", ".yml")):
            continue
        if base not in seen:
            seen.append(base)
    if not seen:
        raise HTTPException(
            status_code=400,
            detail="rule_files contained no valid YAML basenames (.yaml/.yml).",
        )
    return seen


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


def _column_map_for_rules_run(services: BridgeServices, site_id: str) -> dict[str, str]:
    """
    Merge TTL-derived BRICK→column labels with model points (``brick_type`` / ``fdd_input`` → ``external_id``).

    Model entries win on key collision so CSV headers stay aligned with the JSON the operator edited.
    """
    from open_fdd.desktop.services.brick_service import BrickService
    from open_fdd.engine.column_map_from_model import build_column_map_from_model_points

    model = services.model.load()
    by_model = build_column_map_from_model_points(model, site_id)
    try:
        ttl_map = BrickService(ttl_path=services.ttl.ttl_path).resolve_column_map()
    except Exception:
        _log.debug("Brick column map from TTL unavailable", exc_info=True)
        ttl_map = {}
    return {**ttl_map, **by_model}


class CsvIngestBody(BaseModel):
    site_id: str
    source: str = "csv"
    csv_path: str
    equipment_id: str | None = None


class ModelImportBody(BaseModel):
    payload: "ModelPayload"
    replace: bool = True


class PlotsFddFrameBody(BaseModel):
    """
    Load a merged timeseries window and append FDD fault columns for Plotly (same row cap as plot endpoints).

    This is the primary automation surface for “run rules and get a plottable frame”: agents and UIs should POST here
    instead of shelling out to YAML editors. Bounds/flatline rules coerce numeric strings at evaluation time; values
    with embedded units still need **POST /timeseries/clean-metrics** (commit) upstream.
    """

    site_id: str
    rules_path: str
    sources: list[str] = Field(default_factory=lambda: ["csv", "weather", "onboard", "bacnet"])
    limit: int = 5000
    join_how: Literal["inner", "left", "outer", "right"] = "outer"
    start_ts: str | None = None
    end_ts: str | None = None
    rule_files: list[str] | None = None
    skip_missing_columns: bool = True
    chunk_rows: int = 0


class ApplySiteProfilesBody(BaseModel):
    """Apply a declarative ``site_profiles.yaml`` from the repository ``examples/`` tree (ingest + BRICK map + rules copy)."""

    profiles_yaml: str
    reset: bool = True


class AssistantDataModelOpenclawBody(BaseModel):
    """Optional limits for ``POST /assistant/data-model-openclaw``."""

    model_config = ConfigDict(extra="ignore")
    max_rule_bytes: int = Field(default=800_000, ge=10_000, le=5_000_000)
    raw_content_max_chars: int = Field(default=400_000, ge=10_000, le=2_000_000)


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
    #: YAML basenames under ``rules_path`` (e.g. ``["ahu_sat.yaml"]``). Omit or empty = all rules.
    rule_files: list[str] | None = None
    #: If True, rules that need columns missing from the frame are skipped (logged) instead of failing the run.
    skip_missing_columns: bool = False


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


class TimeseriesCleanBody(BaseModel):
    """Coerce string metrics with embedded units (Grafana exports) to floats for FDD rules."""

    site_id: str
    source: str = "csv"
    columns: list[str] | None = None
    commit: bool = False
    preview_limit: int = Field(default=12, ge=1, le=200)


class TimeseriesPlotReadinessBody(BaseModel):
    """Same load path as Plots / FDD: single ``source`` or merged ``sources`` + optional time window."""

    site_id: str
    source: str = "csv"
    sources: list[str] | None = None
    join_how: Literal["inner", "left", "outer", "right"] = "outer"
    start_ts: str | None = None
    end_ts: str | None = None
    limit: int = Field(default=5000, ge=1, le=20_000)


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

    @field_validator("session_id")
    @classmethod
    def session_id_nonempty(cls, v: str) -> str:
        s = str(v).strip()
        if not s:
            raise ValueError("session_id must not be empty or whitespace-only")
        return s


class LocalCodexChatBody(BaseModel):
    """Run `codex exec` on the bridge host (same idea as a local subprocess harness)."""

    model_config = ConfigDict(extra="ignore")
    message: str = Field(..., min_length=1, max_length=200_000)
    workdir: str | None = None
    system_context: str | None = Field(None, max_length=100_000)


class OpenFddAgentHistoryLine(BaseModel):
    """One prior turn from the desktop UI thread (sent so Codex sees full context)."""

    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    text: str = Field(..., max_length=120_000)


class OpenFddAgentChatBody(BaseModel):
    """Open-FDD built-in agent: stack-aware Codex turn with SIMPLE/COMPLEX routing."""

    model_config = ConfigDict(extra="ignore")
    message: str = Field(..., min_length=1, max_length=200_000)
    workdir: str | None = None
    task_summary: str | None = Field(None, max_length=8000)
    force_class: Literal["simple", "complex"] | None = None
    system_context: str | None = Field(None, max_length=100_000)
    conversation_history: list[OpenFddAgentHistoryLine] | None = None

    @field_validator("conversation_history", mode="after")
    @classmethod
    def _cap_conversation_history(cls, v: list[OpenFddAgentHistoryLine] | None) -> list[OpenFddAgentHistoryLine] | None:
        if not v:
            return v
        return v[-120:] if len(v) > 120 else v


class TimeseriesPurgeBody(BaseModel):
    source: str | None = None
    site_id: str | None = None
    prune_points: bool = False


class RuleUploadBody(BaseModel):
    filename: str
    content: str


class RulePutBody(BaseModel):
    content: str


def _try_parse_rule_yaml(text: str) -> tuple[Any, str | None]:
    try:
        doc = yaml.safe_load(text)
        return doc, None
    except yaml.YAMLError as exc:
        return None, str(exc)


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


def _normalize_import_model_payload(
    payload: dict[str, Any],
    *,
    existing_site_ids: frozenset[str] | None = None,
    existing_equipment_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    Best-effort repair for LLM-shaped imports: ensure site rows exist for point site_ids
    and minimal equipment rows for referenced equipment_ids (common when ChatGPT emits points-only JSON).

    When appending to an existing model, pass ``existing_site_ids`` / ``existing_equipment_ids`` so rows
    already on disk are not duplicated by synthesis.
    """
    sites = [dict(s) for s in (payload.get("sites") or []) if isinstance(s, dict)]
    equipment = [dict(e) for e in (payload.get("equipment") or []) if isinstance(e, dict)]
    points = [dict(p) for p in (payload.get("points") or []) if isinstance(p, dict)]

    site_ids_pts = {str(p.get("site_id")) for p in points if p.get("site_id")}
    site_ids_existing = {str(s.get("id")) for s in sites if s.get("id")}
    if existing_site_ids:
        site_ids_existing |= set(existing_site_ids)
    missing_sites = site_ids_pts - site_ids_existing
    for sid in sorted(missing_sites):
        sites.append({"id": sid, "name": "Imported site"})

    site_ids_existing = {str(s.get("id")) for s in sites if s.get("id")}
    eq_ids_pts = {
        str(p.get("equipment_id"))
        for p in points
        if p.get("equipment_id") and str(p.get("equipment_id")).strip()
    }
    eq_ids_existing = {str(e.get("id")) for e in equipment if e.get("id")}
    if existing_equipment_ids:
        eq_ids_existing |= set(existing_equipment_ids)
    for eqid in sorted(eq_ids_pts - eq_ids_existing):
        sid = next(
            (str(p.get("site_id")) for p in points if str(p.get("equipment_id") or "") == eqid and p.get("site_id")),
            None,
        )
        if not sid:
            sid = next(iter(sorted(site_ids_existing)), None)
        if not sid:
            continue
        equipment.append(
            {
                "id": eqid,
                "site_id": sid,
                "name": "Equipment (auto)",
                "equipment_type": "Air_Handling_Unit",
            },
        )
    return {"sites": sites, "equipment": equipment, "points": points}


def _examples_pack_root() -> Path | None:
    """Repository ``examples/`` directory (bundled CSV + profile packs); ``None`` if missing."""
    root = Path(__file__).resolve().parents[2] / "examples"
    return root.resolve() if root.is_dir() else None


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
            {"name": "timeseries", "description": "Feather-backed query, bounds, plots, FDD overlay frame, and purge endpoints."},
            {
                "name": "data_prep",
                "description": "Agent-friendly timeseries cleaning (strip Grafana-style units) before BRICK mapping and FDD.",
            },
            {"name": "rules", "description": "Rule execution, rule file management, and defaults."},
            {"name": "config", "description": "Weather, BACnet, and Onboard runtime configuration."},
            {"name": "sparql", "description": "SPARQL query endpoints for desktop TTL graph."},
            {"name": "system", "description": "Resource and storage stats."},
            {"name": "assistant", "description": "Agent/human handoff: readiness links and declarative site profile apply."},
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
        try:
            candidate_path = Path(candidate).expanduser()
            if not candidate_path.is_absolute():
                candidate_path = (rules_root / candidate_path).resolve()
            else:
                candidate_path = candidate_path.resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid rules_path: {candidate}") from exc
        if rules_root == candidate_path or rules_root in candidate_path.parents:
            if not candidate_path.exists():
                raise HTTPException(status_code=400, detail=f"rules_path does not exist: {candidate}")
            return str(candidate_path)
        ex_root = _examples_pack_root()
        if ex_root is not None and (ex_root == candidate_path or ex_root in candidate_path.parents):
            if not candidate_path.exists():
                raise HTTPException(status_code=400, detail=f"rules_path does not exist: {candidate}")
            return str(candidate_path)
        _log.warning(
            "rules_path rejected: outside managed rules directory (candidate=%r resolved=%r rules_root=%r)",
            candidate,
            str(candidate_path),
            str(rules_root),
        )
        raise HTTPException(status_code=400, detail="rules_path must be inside managed rules directory")

    def _safe_sync_ttl() -> str | None:
        try:
            services.ttl.sync()
            return None
        except Exception as exc:  # noqa: BLE001
            _log.exception("TTL sync failed")
            return str(exc)

    def _memory_info_proc_linux() -> tuple[int, int] | None:
        """``/proc/meminfo`` (MemTotal + MemAvailable or MemFree+Cached+Buffers)."""
        path = Path("/proc/meminfo")
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        mem_total_kb: int | None = None
        mem_avail_kb: int | None = None
        mem_free_kb: int | None = None
        cached_kb = 0
        buffers_kb = 0
        for line in text.splitlines():
            if line.startswith("MemTotal:"):
                mem_total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_avail_kb = int(line.split()[1])
            elif line.startswith("MemFree:"):
                mem_free_kb = int(line.split()[1])
            elif line.startswith("Cached:"):
                cached_kb = int(line.split()[1])
            elif line.startswith("Buffers:"):
                buffers_kb = int(line.split()[1])
        if mem_total_kb is None:
            return None
        if mem_avail_kb is None:
            if mem_free_kb is None:
                return None
            mem_avail_kb = mem_free_kb + cached_kb + buffers_kb
        total = mem_total_kb * 1024
        avail = min(mem_avail_kb * 1024, total)
        return total, avail

    def _memory_info_darwin() -> tuple[int, int] | None:
        """macOS: ``sysctl hw.memsize`` + ``vm_stat`` (free + inactive + speculative pages)."""
        try:
            r = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r.returncode != 0:
                return None
            total = int(r.stdout.strip())
        except (ValueError, OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            return None
        try:
            r2 = subprocess.run(
                ["/usr/bin/vm_stat"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r2.returncode != 0 or not (r2.stdout or "").strip():
                return None
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            return None
        lines = r2.stdout.splitlines()
        page_size = 4096
        if lines and "page size of" in lines[0] and "bytes" in lines[0]:
            try:
                chunk = lines[0].split("page size of", 1)[1]
                page_size = int(chunk.split("bytes", 1)[0].strip())
            except (ValueError, IndexError):
                pass
        pages: dict[str, int] = {}
        for line in lines:
            s = line.strip()
            for key in ("Pages free:", "Pages inactive:", "Pages speculative:"):
                if s.startswith(key):
                    try:
                        pages[key] = int(s.split(":", 1)[1].strip().rstrip("."))
                    except (ValueError, IndexError):
                        pass
        free_p = pages.get("Pages free:", 0)
        inact_p = pages.get("Pages inactive:", 0)
        spec_p = pages.get("Pages speculative:", 0)
        avail = min((free_p + inact_p + spec_p) * page_size, total)
        return total, avail

    def _memory_info_posix_sysconf() -> tuple[int, int] | None:
        try:
            pages = int(os.sysconf("SC_PHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
        except (ValueError, OSError, KeyError, AttributeError):
            return None
        try:
            avail_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        except (ValueError, OSError, KeyError, AttributeError):
            avail_pages = pages
        total = pages * page_size
        avail = avail_pages * page_size
        return total, avail

    def _memory_info() -> dict[str, int | float]:
        total = 0
        avail = 0
        try:
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
                if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    raise OSError("GlobalMemoryStatusEx failed")
                total = int(stat.ullTotalPhys)
                avail = int(stat.ullAvailPhys)
            elif Path("/proc/meminfo").is_file():
                got = _memory_info_proc_linux()
                if got:
                    total, avail = got
            elif platform.system() == "Darwin":
                got = _memory_info_darwin()
                if got:
                    total, avail = got
            if total == 0 and os.name != "nt":
                got = _memory_info_posix_sysconf()
                if got:
                    total, avail = got
        except Exception:  # noqa: BLE001
            _log.exception("memory snapshot failed")
            total, avail = 0, 0
        used = max(0, total - avail)
        pct = round((used / total) * 100, 2) if total > 0 else 0.0
        return {
            "total_bytes": total,
            "available_bytes": avail,
            "used_bytes": used,
            "used_percent": pct,
        }

    def _disk_info() -> dict[str, int | float | str]:
        for target in (Path.home(), Path.cwd()):
            try:
                if not target.exists():
                    continue
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
            except OSError:
                continue
        return {
            "path": "",
            "total_bytes": 0,
            "free_bytes": 0,
            "used_bytes": 0,
            "used_percent": 0.0,
        }

    def _linux_cpu_idle_total() -> tuple[int, int] | None:
        try:
            with open("/proc/stat", encoding="utf-8") as fh:
                line = fh.readline()
        except OSError:
            return None
        parts = line.split()
        if len(parts) < 5 or parts[0] != "cpu":
            return None
        fields = [int(x) for x in parts[1:]]
        while len(fields) < 8:
            fields.append(0)
        user, nice, system, idle, iowait, irq, softirq, steal = fields[:8]
        idle_all = idle + iowait
        busy = user + nice + system + irq + softirq + steal
        total = idle_all + busy
        return idle_all, total

    def _cpu_percent_linux() -> float | None:
        a = _linux_cpu_idle_total()
        if a is None:
            return None
        idle1, total1 = a
        time.sleep(0.12)
        b = _linux_cpu_idle_total()
        if b is None:
            return None
        idle2, total2 = b
        did = idle2 - idle1
        dtot = total2 - total1
        if dtot <= 0:
            return None
        return round(100.0 * (1.0 - did / dtot), 1)

    def _cpu_percent_darwin_host() -> float | None:
        """Approximate host CPU% using Mach ``HOST_CPU_LOAD_INFO`` (macOS / Darwin)."""
        if platform.system() != "Darwin" or os.name == "nt":
            return None
        try:
            libname = ctypes.util.find_library("System")
            libc = ctypes.CDLL(libname) if libname else ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        except OSError:
            try:
                libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            except OSError:
                return None
        HOST_CPU_LOAD_INFO = 3
        KERN_SUCCESS = 0

        class HostCpuLoadInfo(ctypes.Structure):
            _fields_ = [("cpu_ticks", ctypes.c_uint * 4)]

        mach_host_self = libc.mach_host_self
        mach_host_self.argtypes = []
        mach_host_self.restype = ctypes.c_uint

        host_statistics = libc.host_statistics
        host_statistics.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(HostCpuLoadInfo),
            ctypes.POINTER(ctypes.c_int),
        ]
        host_statistics.restype = ctypes.c_int

        def sample() -> tuple[int, int] | None:
            port = mach_host_self()
            data = HostCpuLoadInfo()
            count = ctypes.c_int(4)
            kr = host_statistics(port, HOST_CPU_LOAD_INFO, ctypes.byref(data), ctypes.byref(count))
            if kr != KERN_SUCCESS:
                return None
            user, nice, system, idle_ = (int(data.cpu_ticks[i]) for i in range(4))
            busy = user + nice + system
            tot = idle_ + busy
            return idle_, tot

        try:
            a = sample()
            if a is None:
                return None
            idle1, tot1 = a
            time.sleep(0.12)
            b = sample()
            if b is None:
                return None
            idle2, tot2 = b
            did = idle2 - idle1
            dtot = tot2 - tot1
            if dtot <= 0:
                return None
            return round(100.0 * (1.0 - did / dtot), 1)
        except Exception:  # noqa: BLE001
            return None

    def _cpu_percent_windows() -> float | None:
        class FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", ctypes.wintypes.DWORD),
                ("dwHighDateTime", ctypes.wintypes.DWORD),
            ]

        def ft64(ft: FILETIME) -> int:
            return int(ft.dwLowDateTime) + (int(ft.dwHighDateTime) << 32)

        idle1, k1, u1 = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(k1), ctypes.byref(u1)):
            return None
        time.sleep(0.12)
        idle2, k2, u2 = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(k2), ctypes.byref(u2)):
            return None
        idle_delta = ft64(idle2) - ft64(idle1)
        total_delta = (ft64(k2) - ft64(k1)) + (ft64(u2) - ft64(u1))
        if total_delta <= 0:
            return None
        return round(100.0 - (100.0 * idle_delta / total_delta), 1)

    def _cpu_info() -> dict[str, Any]:
        cores = int(os.cpu_count() or 1)
        out: dict[str, Any] = {"logical_cores": cores, "cpu_percent": None}
        try:
            if os.name == "nt":
                out["cpu_percent"] = _cpu_percent_windows()
            elif Path("/proc/stat").is_file():
                pct = _cpu_percent_linux()
                if pct is not None:
                    out["cpu_percent"] = pct
                else:
                    try:
                        load1, _, _ = os.getloadavg()
                        out["load_average_1m"] = round(float(load1), 2)
                    except (OSError, AttributeError):
                        pass
            elif platform.system() == "Darwin":
                pct = _cpu_percent_darwin_host()
                if pct is not None:
                    out["cpu_percent"] = pct
                else:
                    try:
                        load1, _, _ = os.getloadavg()
                        out["load_average_1m"] = round(float(load1), 2)
                    except (OSError, AttributeError):
                        pass
            else:
                try:
                    load1, _, _ = os.getloadavg()
                    out["load_average_1m"] = round(float(load1), 2)
                except (OSError, AttributeError):
                    pass
        except Exception:  # noqa: BLE001
            _log.exception("cpu snapshot failed")
        return out

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

    @app.get("/local-codex/diagnostics", tags=["local-codex"])
    def local_codex_diagnostics() -> dict[str, Any]:
        return local_codex_cli.gather_diagnostics()

    @app.post("/local-codex/install-cli", tags=["local-codex"])
    def local_codex_install_cli() -> dict[str, Any]:
        """Install the OpenAI Codex CLI globally via npm on the bridge host (can take several minutes)."""
        if not _allow_local_codex_install_cli():
            raise HTTPException(
                status_code=403,
                detail=(
                    "Local Codex npm install is disabled by default. Set OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI=1 on "
                    "the bridge host to allow POST /local-codex/install-cli (start-local scripts set this for local dev)."
                ),
            )
        return local_codex_cli.run_npm_install_codex_global()

    @app.post("/local-codex/logout", tags=["local-codex"])
    def local_codex_logout() -> dict[str, Any]:
        """Run ``codex logout`` on the bridge host (same as signing out in a terminal there)."""
        codex = local_codex_cli.resolve_codex_executable()
        if not codex:
            raise HTTPException(
                status_code=503,
                detail="codex CLI not found on this machine. Install with npm install -g @openai/codex "
                "or set OFDD_CODEX_CMD to the full path to codex.cmd / codex.",
            )
        return local_codex_cli.run_codex_logout(codex)

    @app.post("/local-codex/chat", tags=["local-codex"])
    def local_codex_chat(body: LocalCodexChatBody) -> dict[str, Any]:
        codex = local_codex_cli.resolve_codex_executable()
        if not codex:
            raise HTTPException(
                status_code=503,
                detail="codex CLI not found on this machine. Install with npm install -g @openai/codex "
                "or set OFDD_CODEX_CMD to the full path to codex.cmd / codex.",
            )
        workdir = local_codex_cli.resolve_workdir(body.workdir)
        if not workdir.is_dir():
            raise HTTPException(status_code=400, detail=f"workdir is not a directory: {workdir}")
        stdin_text = local_codex_cli.build_chat_stdin(
            user_message=body.message,
            system_context=body.system_context,
        )
        return local_codex_cli.run_codex_exec(codex, workdir, stdin_text=stdin_text)

    @app.get("/openfdd-agent/context", tags=["openfdd-agent"])
    def openfdd_agent_context() -> dict[str, Any]:
        """Ports and URLs for the built-in agent (merge of env + optional bootstrap JSON)."""
        return build_agent_bootstrap_context()

    @app.post("/openfdd-agent/chat", tags=["openfdd-agent"])
    def openfdd_agent_chat(body: OpenFddAgentChatBody) -> dict[str, Any]:
        hist: list[tuple[str, str]] | None = None
        if body.conversation_history:
            hist = [(ln.role, ln.text) for ln in body.conversation_history]
        result = run_openfdd_agent_turn(
            message=body.message,
            workdir_raw=body.workdir,
            task_summary=body.task_summary,
            force_class=body.force_class,
            system_context=body.system_context,
            conversation_history=hist,
        )
        if result.get("error") == "codex_cli_missing":
            raise HTTPException(status_code=503, detail=str(result.get("detail") or "codex CLI missing"))
        if result.get("error") == "bad_workdir":
            raise HTTPException(status_code=400, detail=str(result.get("detail") or "bad workdir"))
        return result

    @app.post("/openfdd-claw/codex/device/start", tags=["openfdd-claw"])
    def codex_device_start() -> dict[str, Any]:
        try:
            return codex_device_login.start_device_login()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/openfdd-claw/codex/device/poll", tags=["openfdd-claw"])
    def codex_device_poll(body: CodexDevicePollBody) -> dict[str, Any]:
        return codex_device_login.poll_device_login(body.session_id)

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
        if body.replace:
            normalized = _normalize_import_model_payload(normalized)
        else:
            cur = services.model.load()
            ext_sites = frozenset(
                str(s.get("id")) for s in (cur.get("sites") or []) if isinstance(s, dict) and s.get("id")
            )
            ext_eq = frozenset(
                str(e.get("id")) for e in (cur.get("equipment") or []) if isinstance(e, dict) and e.get("id")
            )
            normalized = _normalize_import_model_payload(
                normalized,
                existing_site_ids=ext_sites,
                existing_equipment_ids=ext_eq,
            )
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
            out = services.ingest.ingest_csv(
                csv_path=csv_path,
                site_id=body.site_id,
                source=body.source,
                equipment_id=body.equipment_id,
            )
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
        equipment_id: str | None = Form(None),
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
            out = services.ingest.ingest_csv(
                csv_path=tmp_path,
                site_id=site_id,
                source=source,
                equipment_id=equipment_id,
            )
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
        try:
            safe_rules_path = _safe_rules_path(body.rules_path)
        except HTTPException:
            raise
        rule_files_norm = _normalize_rule_files_basenames(body.rule_files)
        if frame.empty:
            return {
                "input_rows": 0,
                "output_rows": 0,
                "columns": [],
                "fault_totals": {},
                "preview": "",
                "rule_files_filter": rule_files_norm,
                "skip_missing_columns": bool(body.skip_missing_columns),
                **load_meta,
            }
        cmap = _column_map_for_rules_run(services, body.site_id)
        try:
            out = run_rule_loop_batched(
                frame,
                RuleLoopConfig(
                    rules_path=safe_rules_path,
                    chunk_rows=int(body.chunk_rows or 0),
                    target_memory_fraction=float(body.target_memory_fraction or 0.25),
                    rule_files=rule_files_norm,
                    skip_missing_columns=bool(body.skip_missing_columns),
                    column_map=cmap or None,
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{exc}. Hint: this usually means a rule references a sensor column not present "
                    "in the selected source/window; pass a non-empty ``sources`` list on this endpoint to join "
                    "those drivers on ``timestamp`` (or use a timeseries route that loads all default drivers for you), "
                    "map/upload matching points, narrow rule_files to one YAML, or set skip_missing_columns=true to skip incompatible rules. "
                    "Joined frames suffix metrics as metric_driver (e.g. _csv); the engine maps BRICK labels to those automatically when possible. "
                    "Bounds/flatline coerce numeric strings; if you still see dtype errors, use POST /timeseries/clean-metrics or fix column dtypes."
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
            "rule_files_filter": rule_files_norm,
            "skip_missing_columns": bool(body.skip_missing_columns),
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

    @app.post("/timeseries/clean-metrics", tags=["data_prep"])
    def timeseries_clean_metrics(body: TimeseriesCleanBody) -> dict[str, Any]:
        """
        Preview or commit numeric coercion for one driver ``source`` (usually ``csv``).

        Omit ``columns`` to auto-select string columns that look like ``12.3 psi`` / ``70 °F``.
        Set ``commit:true`` to purge and rewrite Feather for that site+source (destructive).
        """
        return services.ingest.clean_timeseries_metrics(
            site_id=body.site_id,
            source=body.source,
            columns=body.columns,
            commit=bool(body.commit),
            preview_limit=int(body.preview_limit),
        )

    @app.post(
        "/timeseries/plot-readiness",
        tags=["data_prep"],
        response_model=TimeseriesPlotReadiness,
    )
    def timeseries_plot_readiness(body: TimeseriesPlotReadinessBody) -> TimeseriesPlotReadiness:
        """
        Pydantic-validated report: which columns plot as numeric lines vs need ``clean-metrics`` / mapping fixes.

        Agents should call this before ``/plots/fdd-frame`` when diagnosing flat or empty Plotly traces.
        """
        merge_sources = [str(s).strip() for s in (body.sources or []) if str(s).strip()]
        try:
            if merge_sources:
                frame, _used = services.ingest.load_merged_sources_frame_window(
                    site_id=body.site_id,
                    sources=merge_sources,
                    start_ts=body.start_ts,
                    end_ts=body.end_ts,
                    join_how=str(body.join_how),
                )
            else:
                frame = services.ingest.load_source_frame_window(
                    source=body.source,
                    site_id=body.site_id,
                    start_ts=body.start_ts,
                    end_ts=body.end_ts,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        cap = max(1, min(int(body.limit), 20_000))
        tail = frame.tail(cap) if not frame.empty else frame
        return analyze_dataframe_for_plot(tail)

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
    def plots_frame(
        site_id: str,
        source: str = "csv",
        limit: int = 5000,
        include_readiness: bool = False,
    ) -> dict[str, Any]:
        frame = services.ingest.load_source_frame(source=source, site_id=site_id)
        if frame.empty:
            out: dict[str, Any] = {"columns": [], "rows": []}
            if include_readiness:
                out["readiness"] = analyze_dataframe_for_plot(frame).model_dump()
            return out
        cap = max(1, min(int(limit), 20_000))
        work = frame.tail(cap).copy()
        readiness_dict: dict[str, Any] | None = None
        if include_readiness:
            readiness_dict = analyze_dataframe_for_plot(work).model_dump()
        work = work.where(pd.notnull(work), None)
        if "timestamp" in work.columns:
            work["timestamp"] = work["timestamp"].astype(str)
        return {
            "columns": [str(c) for c in work.columns],
            "rows": _plot_frame_records_json_safe(work),
            **({"readiness": readiness_dict} if readiness_dict is not None else {}),
        }

    @app.get("/plots/site-frame", tags=["timeseries"])
    def plots_site_frame(
        site_id: str,
        sources: str = "csv,weather,onboard,bacnet",
        limit: int = 5000,
        join_how: str = "outer",
        start_ts: str | None = None,
        end_ts: str | None = None,
        include_readiness: bool = False,
    ) -> dict[str, Any]:
        cap = max(1, min(int(limit), 20_000))
        source_list = [s.strip() for s in str(sources).split(",") if s.strip()]
        if not source_list:
            source_list = ["csv"]
        jh = str(join_how or "outer").strip().lower()
        if jh not in {"inner", "left", "outer", "right"}:
            jh = "outer"
        try:
            merged, used_sources = services.ingest.load_merged_sources_frame_window(
                site_id=site_id,
                sources=source_list,
                start_ts=start_ts,
                end_ts=end_ts,
                join_how=jh,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if merged.empty:
            out: dict[str, Any] = {"columns": [], "rows": [], "sources": used_sources}
            if include_readiness:
                out["readiness"] = analyze_dataframe_for_plot(merged).model_dump()
            return out
        ts_col = infer_timestamp_column(merged)
        work = merged.tail(cap).copy()
        readiness_dict: dict[str, Any] | None = None
        if include_readiness:
            readiness_dict = analyze_dataframe_for_plot(work).model_dump()
        work = work.where(pd.notnull(work), None)
        if ts_col in work.columns:
            work[ts_col] = work[ts_col].astype(str)
        return {
            "columns": [str(c) for c in work.columns],
            "rows": _plot_frame_records_json_safe(work),
            "sources": used_sources,
            **({"readiness": readiness_dict} if readiness_dict is not None else {}),
        }

    def _plots_fdd_payload(body: PlotsFddFrameBody) -> dict[str, Any]:
        """
        Merged timeseries for plotting plus FDD fault columns (same row cap as ``/plots/site-frame``).

        Rules execute on the **tail** ``limit`` rows of the merged window (aligned with the plot load path).
        """
        cap = max(1, min(int(body.limit), 20_000))
        cleaned = [str(s).strip() for s in body.sources if str(s).strip()]
        if not cleaned:
            cleaned = ["csv"]
        try:
            merged, used_sources = services.ingest.load_merged_sources_frame_window(
                site_id=body.site_id,
                sources=cleaned,
                start_ts=body.start_ts,
                end_ts=body.end_ts,
                join_how=str(body.join_how),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        safe_rules = _safe_rules_path(body.rules_path)
        rule_files_norm = _normalize_rule_files_basenames(body.rule_files)
        if merged.empty:
            return {
                "columns": [],
                "rows": [],
                "sources": [],
                "fault_totals": {},
                "rule_files_filter": rule_files_norm,
            }
        ts_col = infer_timestamp_column(merged)
        work = merged.tail(cap).copy()
        cmap = _column_map_for_rules_run(services, body.site_id)
        try:
            evaluated = run_rule_loop_batched(
                work,
                RuleLoopConfig(
                    rules_path=safe_rules,
                    chunk_rows=int(body.chunk_rows or 0),
                    rule_files=rule_files_norm,
                    skip_missing_columns=bool(body.skip_missing_columns),
                    column_map=cmap or None,
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        out = evaluated.where(pd.notnull(evaluated), None)
        if ts_col in out.columns:
            out[ts_col] = out[ts_col].astype(str)
        fault_cols = [c for c in out.columns if c.endswith("_flag") or c.endswith("_fault")]
        fault_totals = {c: int(pd.to_numeric(out[c], errors="coerce").fillna(0).sum()) for c in fault_cols}
        return {
            "columns": [str(c) for c in out.columns],
            "rows": _plot_frame_records_json_safe(out),
            "sources": used_sources,
            "fault_totals": fault_totals,
            "rule_files_filter": rule_files_norm,
        }

    @app.post("/plots/fdd-frame", tags=["timeseries"])
    def plots_fdd_frame(body: PlotsFddFrameBody) -> dict[str, Any]:
        return _plots_fdd_payload(body)

    @app.post("/plots/share", tags=["timeseries"])
    def plots_share_create(body: PlotsFddFrameBody) -> dict[str, Any]:
        """Run the same pipeline as ``/plots/fdd-frame`` and persist parameters for a reopenable Claw handoff."""
        from open_fdd.assistant.readiness import ui_public_base_url
        from open_fdd.desktop.storage.plot_share_store import save_plot_share

        result = _plots_fdd_payload(body)
        safe_rules = _safe_rules_path(body.rules_path)
        cleaned = [str(s).strip() for s in body.sources if str(s).strip()] or ["csv"]
        share_id = save_plot_share(
            {
                "site_id": body.site_id,
                "rules_path": safe_rules,
                "sources": cleaned,
                "limit": int(body.limit),
                "join_how": str(body.join_how),
                "start_ts": body.start_ts,
                "end_ts": body.end_ts,
                "rule_files": body.rule_files,
                "skip_missing_columns": bool(body.skip_missing_columns),
                "chunk_rows": int(body.chunk_rows or 0),
                "fault_totals": result.get("fault_totals") or {},
                "columns": result.get("columns") or [],
                "row_count": len(result.get("rows") or []),
            },
        )
        result["share_id"] = share_id
        result["plots_open_url"] = f"{ui_public_base_url().rstrip('/')}/plots?share={urllib.parse.quote(share_id, safe='')}"
        return result

    @app.get("/plots/share/{share_id}", tags=["timeseries"])
    def plots_share_get(share_id: str) -> dict[str, Any]:
        """Return a saved plot+FDD session (no rows); use with ``POST /plots/fdd-frame`` or Plots ``?share=``."""
        from open_fdd.desktop.storage.plot_share_store import load_plot_share

        rec = load_plot_share(share_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="share not found")
        return rec

    @app.get("/assistant/readiness", tags=["assistant"])
    def assistant_readiness() -> dict[str, Any]:
        """Copy-paste handoff for humans or chat agents: deep links, site summary, suggested follow-up."""
        from open_fdd.assistant.readiness import build_readiness_payload

        return build_readiness_payload(services.model.load())

    @app.post("/assistant/apply-site-profiles", tags=["assistant"])
    def assistant_apply_site_profiles(body: ApplySiteProfilesBody) -> dict[str, Any]:
        """
        Run ingest + equipment + BRICK mappings from a YAML pack under ``examples/`` (same schema as the workshop file).

        Intended for agents / OpenClaw-style automation; paths are restricted to the repo ``examples/`` directory.
        """
        from open_fdd.assistant.site_profiles_runner import apply_site_profiles_file

        raw = str(body.profiles_yaml or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="profiles_yaml is required")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(status_code=400, detail="profiles_yaml must be an absolute path")
        resolved = candidate.resolve()
        ex_root = _examples_pack_root()
        if ex_root is None:
            raise HTTPException(status_code=400, detail="examples directory is not available on this install")
        if ex_root not in resolved.parents and resolved != ex_root:
            raise HTTPException(
                status_code=400,
                detail="profiles_yaml must be located under the repository examples/ directory",
            )
        try:
            out = apply_site_profiles_file(
                profiles_yaml=resolved,
                model=services.model,
                ingest=services.ingest,
                ttl=services.ttl,
                reset=bool(body.reset),
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ttl_err = _safe_sync_ttl()
        if ttl_err:
            out["ttl_sync_warning"] = ttl_err
        return out

    @app.post("/assistant/data-model-openclaw", tags=["assistant"])
    def assistant_data_model_openclaw(body: AssistantDataModelOpenclawBody | None = None) -> dict[str, Any]:
        """
        Call the OpenClaw gateway OpenAI-compatible chat API with the current ``/model/export`` JSON plus
        all managed ``*.yaml`` / ``*.yml`` under the desktop rules directory.

        Requires ``OFDD_OPENCLAW_GATEWAY_TOKEN`` (or ``OFDD_CLAW_GATEWAY_TOKEN``) and a reachable gateway
        (default ``OFDD_OPENCLAW_GATEWAY_URL`` = ``http://127.0.0.1:18789``). Returns parsed ``import_ready``
        when the model response is JSON-shaped; otherwise inspect ``raw_content``.
        """
        from open_fdd.assistant.data_model_openclaw import (
            build_data_model_redesign_user_message,
            collect_managed_rule_yaml_texts,
            extract_import_shape_from_llm_output,
        )
        from open_fdd.assistant.data_model_redesign_prompt import DATA_MODEL_REDESIGN_SYSTEM_PROMPT
        from open_fdd.gateway.openclaw_chat import OpenClawGatewayChatClient

        opts = body or AssistantDataModelOpenclawBody()
        model = services.model.load()
        rules_root = _rules_dir().resolve()
        pairs = collect_managed_rule_yaml_texts(rules_root, max_bytes=int(opts.max_rule_bytes))
        if not pairs:
            raise HTTPException(
                status_code=400,
                detail=f"No rule YAML found under managed rules directory: {rules_root}",
            )
        user_msg = build_data_model_redesign_user_message(model, pairs)
        client = OpenClawGatewayChatClient()
        try:
            resp = client.complete_for_task(
                task_summary="Open-FDD data model BRICK redesign from export and rule YAML",
                messages=[
                    {"role": "system", "content": DATA_MODEL_REDESIGN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc)
                + " Set OFDD_OPENCLAW_GATEWAY_TOKEN (OpenClaw gateway.auth.token) and ensure the gateway is running.",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        content = resp.content
        cap = int(opts.raw_content_max_chars)
        raw_out = content if len(content) <= cap else content[:cap] + "\n…[truncated by raw_content_max_chars]…"
        import_ready = extract_import_shape_from_llm_output(content)
        return {
            "rule_files_used": [p[0] for p in pairs],
            "import_ready": import_ready,
            "import_ready_parse_ok": import_ready is not None,
            "raw_content": raw_out,
            "openclaw_task_class": getattr(resp.task_class, "value", str(resp.task_class)),
            "openclaw_route_reason": resp.route_reason,
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

    @app.get("/data-model/testing/rule-data-lineage", tags=["sparql"])
    def data_model_testing_rule_data_lineage(site_id: str | None = None) -> dict[str, Any]:
        """Rule YAML inputs × TTL column map × model points (Feather external_ref) for operator debugging."""
        from open_fdd.desktop.services.fdd_data_lineage import build_fdd_rule_data_lineage

        ttl_path = services.ttl.sync()
        model = services.model.load()
        rules_dir = _rules_dir()
        sid = str(site_id).strip() if site_id and str(site_id).strip() else None
        return build_fdd_rule_data_lineage(model=model, ttl_path=ttl_path, rules_dir=rules_dir, site_id=sid)

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

    @app.get("/rules/export-json", tags=["rules"])
    def export_rules_json() -> dict[str, Any]:
        """
        Full managed rule pack as JSON (YAML text + parsed document per file).

        Intended for agents and humans to share the same view as the FDD Rule Setup UI.
        """
        rules_dir = _rules_dir()
        names = sorted(
            [p.name for p in rules_dir.iterdir() if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}]
        )
        rules: list[dict[str, Any]] = []
        for name in names:
            text = (rules_dir / name).read_text(encoding="utf-8")
            parsed, parse_error = _try_parse_rule_yaml(text)
            rules.append(
                {
                    "filename": name,
                    "yaml": text,
                    "parsed": parsed,
                    "parse_error": parse_error,
                },
            )
        return {"rules_dir": str(rules_dir), "count": len(rules), "rules": rules}

    @app.get("/rules/{filename}", tags=["rules"], response_model=None)
    def get_rule_file(
        filename: str,
        parsed: bool = Query(False, description="If true, return JSON with yaml text and parsed document."),
    ) -> Response | dict[str, Any]:
        safe = _safe_rule_filename(filename)
        path = _rules_dir() / safe
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"Rule file not found: {safe}")
        text = path.read_text(encoding="utf-8")
        if parsed:
            doc, parse_error = _try_parse_rule_yaml(text)
            return {
                "filename": safe,
                "rules_dir": str(_rules_dir()),
                "yaml": text,
                "parsed": doc,
                "parse_error": parse_error,
            }
        return Response(content=text, media_type="text/plain; charset=utf-8")

    @app.post("/rules", tags=["rules"])
    def upload_rule_file(body: RuleUploadBody) -> dict[str, Any]:
        safe = _safe_rule_filename(body.filename.strip())
        path = _rules_dir() / safe
        path.write_text(body.content, encoding="utf-8")
        return {"filename": safe, "size": len(body.content)}

    @app.put("/rules/{filename}", tags=["rules"])
    def put_rule_file(filename: str, body: RulePutBody) -> dict[str, Any]:
        """Update an existing rule file in the managed pack (same disk location the UI lists)."""
        safe = _safe_rule_filename(filename)
        path = _rules_dir() / safe
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail=f"Rule file not found: {safe}")
        path.write_text(body.content, encoding="utf-8")
        return {"filename": safe, "size": len(body.content), "updated": True}

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
            "cpu": _cpu_info(),
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
