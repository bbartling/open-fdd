from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any
import logging

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched
from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.paths import default_rules_root

_log = logging.getLogger(__name__)

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
    payload: dict[str, Any]
    replace: bool = True


class RuleRunBody(BaseModel):
    site_id: str
    source: str = "csv"
    rules_path: str
    chunk_rows: int = 0


class SiteCreateBody(BaseModel):
    name: str


class SparqlQueryBody(BaseModel):
    query: str


class SiteRulePackBody(BaseModel):
    rule_pack: str


class TimeseriesPurgeBody(BaseModel):
    source: str | None = None
    site_id: str | None = None
    prune_points: bool = False


def create_app() -> FastAPI:
    app = FastAPI(title="open-fdd desktop bridge")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    services = _build_services()
    def _safe_sync_ttl() -> str | None:
        try:
            path = services.ttl.sync()
            return str(path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("TTL sync failed")
            return str(exc)

    app.state.ttl_sync_interval_seconds = 30
    app.state.last_ttl_sync_iso = ""
    app.state.ttl_sync_error = ""

    async def _ttl_sync_loop() -> None:
        while True:
            try:
                path = services.ttl.sync()
                app.state.last_ttl_sync_iso = str(path)
                app.state.ttl_sync_error = ""
            except Exception as exc:  # pragma: no cover - defensive runtime loop
                app.state.ttl_sync_error = str(exc)
            await asyncio.sleep(int(app.state.ttl_sync_interval_seconds))

    @app.on_event("startup")
    async def startup_event() -> None:
        app.state.ttl_sync_task = asyncio.create_task(_ttl_sync_loop())

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        task = getattr(app.state, "ttl_sync_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/model/export")
    def model_export() -> dict[str, Any]:
        return services.model.load()

    @app.get("/sites")
    def list_sites() -> list[dict[str, Any]]:
        return services.model.load().get("sites", [])

    @app.post("/sites")
    def create_site(body: SiteCreateBody) -> dict[str, Any]:
        site = services.model.create_site(body.name.strip() or "Site")
        ttl_error = _safe_sync_ttl()
        if ttl_error:
            site = {**site, "warning": f"TTL sync failed: {ttl_error}"}
        return site

    @app.delete("/sites/{site_id}")
    def delete_site(site_id: str) -> dict[str, int]:
        out = services.model.delete_site(site_id)
        ttl_error = _safe_sync_ttl()
        if ttl_error:
            return {**out, "ttl_sync_warning": ttl_error}
        return out

    @app.post("/sites/{site_id}/rule-pack")
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

    @app.post("/model/import")
    def model_import(body: ModelImportBody) -> dict[str, int]:
        return services.model.import_json(body.payload, replace=body.replace)

    @app.post("/model/ttl/sync")
    def model_ttl_sync() -> dict[str, str]:
        path = services.ttl.sync()
        return {"path": str(path)}

    @app.get("/model/ttl/status")
    def model_ttl_status() -> dict[str, Any]:
        return {
            "ttl_path": str(services.ttl.ttl_path),
            "sync_interval_seconds": int(app.state.ttl_sync_interval_seconds),
            "last_sync_path": app.state.last_ttl_sync_iso,
            "last_sync_error": app.state.ttl_sync_error,
        }

    @app.post("/ingest/csv")
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
            return services.ingest.ingest_csv(csv_path=csv_path, site_id=body.site_id, source=body.source)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/rules/run")
    def rules_run(body: RuleRunBody) -> dict[str, Any]:
        frame = services.ingest.load_source_frame(source=body.source, site_id=body.site_id)
        if frame.empty:
            return {"input_rows": 0, "output_rows": 0, "columns": [], "fault_totals": {}, "preview": ""}
        out = run_rule_loop_batched(
            frame,
            RuleLoopConfig(rules_path=body.rules_path, chunk_rows=int(body.chunk_rows or 0)),
        )
        fault_cols = [c for c in out.columns if c.endswith("_flag")]
        fault_totals = {c: int(out[c].sum()) for c in fault_cols}
        preview = out.tail(10).to_string(index=False)
        return {
            "input_rows": len(frame.index),
            "output_rows": len(out.index),
            "columns": [str(c) for c in out.columns],
            "fault_totals": fault_totals,
            "preview": preview,
        }

    @app.get("/data-model/testing/predefined")
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
        ]

    @app.post("/data-model/testing/query")
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
        for row in graph.query(body.query):
            row_map = row.asdict() if hasattr(row, "asdict") else {}
            if not columns:
                columns = [str(k) for k in row_map.keys()]
            rows.append({k: str(v) for k, v in row_map.items()})
        return {"columns": columns, "rows": rows}

    @app.get("/rules/defaults")
    def list_default_rules() -> dict[str, Any]:
        source_dir = Path(__file__).resolve().parents[1] / "default_rules" / "ahu_vav"
        files = sorted(source_dir.glob("*.yaml"))
        return {
            "rule_pack": "ahu_vav",
            "source_dir": str(source_dir),
            "files": [f.name for f in files],
        }

    @app.post("/rules/defaults/install")
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

    @app.get("/storage/timeseries/stats")
    def timeseries_stats() -> dict[str, int]:
        return services.ingest.feather_store.stats()

    @app.post("/storage/timeseries/purge")
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


def run_desktop_bridge(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_desktop_bridge()
