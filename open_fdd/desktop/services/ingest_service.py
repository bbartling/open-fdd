from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.desktop.drivers.onboard_driver import run_onboard_scrape
from open_fdd.desktop.drivers.weather_driver import run_weather_fetch
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.connectors import TimeSeriesConnector
from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class IngestService:
    model_service: ModelService = field(default_factory=ModelService)
    feather_store: FeatherStore = field(default_factory=FeatherStore)
    connector: TimeSeriesConnector | None = None

    def __post_init__(self) -> None:
        if self.connector is None:
            from open_fdd.desktop.storage.connectors import FeatherConnector

            self.connector = FeatherConnector(self.feather_store)

    def ingest_csv(self, *, csv_path: str | Path, site_id: str, source: str = "csv") -> dict[str, Any]:
        result = self.connector.ingest_csv(csv_path=str(csv_path), source=source, site_id=site_id)
        metric_columns = [str(c) for c in result.get("metrics", [])]
        rows = int(result.get("rows", 0))
        dropped_rows = int(result.get("dropped_rows", 0))
        target = str(result.get("storage_path", ""))
        feather_path = str(result.get("feather_path", ""))
        storage_ref = str(result.get("storage_ref") or target)
        with self.model_service.transaction() as model:
            for metric in metric_columns:
                self._upsert_point_for_metric(
                    model=model,
                    site_id=site_id,
                    metric=metric,
                    source=source,
                    storage_ref=storage_ref,
                )
        return {
            "rows": rows,
            "storage_path": target,
            "feather_path": feather_path,
            "metrics": metric_columns,
            "dropped_rows": dropped_rows,
        }

    def ingest_weather(self, *, site_id: str, days_back: int = 1) -> dict[str, Any]:
        result = run_weather_fetch(store=self.connector, site_id=site_id, days_back=days_back)
        return {"rows": result.rows, "source": "weather"}

    def ingest_onboard(self, *, site_id: str) -> dict[str, Any]:
        result = run_onboard_scrape(store=self.connector, site_id=site_id)
        if not result.success:
            return {
                "rows": result.rows,
                "source": result.source,
                "success": False,
                "error": result.error or "Onboard ingest failed.",
            }
        metrics = [str(m) for m in (result.metrics or [])]
        storage_ref = str(result.storage_ref or "")
        with self.model_service.transaction() as model:
            for metric in metrics:
                md = (result.point_metadata or {}).get(metric, {})
                self._upsert_point_for_metric(
                    model=model,
                    site_id=site_id,
                    metric=metric,
                    source=result.source,
                    storage_ref=storage_ref,
                    brick_type_override=str(md.get("brick_type") or "Point"),
                    fdd_input_override=(str(md.get("fdd_input")) if md.get("fdd_input") is not None else None),
                    unit_override=(str(md.get("unit")) if md.get("unit") is not None else None),
                )
        return {"rows": result.rows, "source": result.source, "success": True}

    def load_source_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.connector.read_frame(source=source, site_id=site_id)

    def purge_timeseries(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        return self.connector.purge(source=source, site_id=site_id)

    def _upsert_point_for_metric(
        self,
        *,
        model: dict[str, Any],
        site_id: str,
        metric: str,
        source: str,
        storage_ref: str,
        brick_type_override: str | None = None,
        fdd_input_override: str | None = None,
        unit_override: str | None = None,
    ) -> None:
        existing = next(
            (
                p
                for p in model["points"]
                if p.get("site_id") == site_id
                and p.get("external_id") == metric
                and isinstance(p.get("metadata"), dict)
                and p["metadata"].get("source") == source
            ),
            None,
        )
        if existing:
            md = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
            md["external_ref"] = storage_ref
            md["source"] = source
            existing["metadata"] = md
            if brick_type_override:
                existing["brick_type"] = brick_type_override
            if fdd_input_override is not None:
                existing["fdd_input"] = fdd_input_override
            if unit_override is not None:
                existing["unit"] = unit_override
            return
        model["points"].append(
            {
                "id": self.model_service.store.id_str(),
                "site_id": site_id,
                "equipment_id": None,
                "external_id": metric,
                "brick_type": brick_type_override or "Point",
                "fdd_input": fdd_input_override,
                "unit": unit_override,
                "metadata": {
                    "external_ref": storage_ref,
                    "source": source,
                },
            }
        )

