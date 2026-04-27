from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.desktop.drivers.csv_driver import infer_timestamp_column, ingest_csv_to_feather
from open_fdd.desktop.drivers.onboard_driver import run_onboard_scrape
from open_fdd.desktop.drivers.weather_driver import run_weather_fetch
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.connectors import FeatherConnector, TimeSeriesConnector
from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class IngestService:
    model_service: ModelService = field(default_factory=ModelService)
    feather_store: FeatherStore = field(default_factory=FeatherStore)
    connector: TimeSeriesConnector | None = None

    def __post_init__(self) -> None:
        if self.connector is None:
            self.connector = FeatherConnector(self.feather_store)

    def ingest_csv(self, *, csv_path: str | Path, site_id: str, source: str = "csv") -> dict[str, Any]:
        if isinstance(self.connector, FeatherConnector):
            result = ingest_csv_to_feather(csv_path=csv_path, source=source, site_id=site_id, store=self.feather_store)
            metric_columns = result.metric_columns
            rows = result.rows
            dropped_rows = result.dropped_rows
            target = str(result.file_path)
            feather_path = str(result.file_path)
        else:
            frame = pd.read_csv(csv_path)
            original_len = len(frame.index)
            if frame.empty:
                metric_columns = []
                rows = 0
                dropped_rows = 0
            else:
                ts_col = infer_timestamp_column([str(c) for c in frame.columns])
                frame[ts_col] = pd.to_datetime(frame[ts_col], errors="coerce", utc=True)
                frame = frame[frame[ts_col].notna()].copy()
                metric_columns = [str(c) for c in frame.columns if str(c) != ts_col]
                rows = len(frame.index)
                dropped_rows = original_len - rows
            target = self.connector.write_frame(source=source, site_id=site_id, frame=frame)
            feather_path = ""
        with self.model_service.transaction() as model:
            for metric in metric_columns:
                self._upsert_point_for_metric(model=model, site_id=site_id, metric=metric, source=source)
        return {
            "rows": rows,
            "storage_path": target,
            "feather_path": feather_path,
            "metrics": metric_columns,
            "dropped_rows": dropped_rows,
        }

    def ingest_weather(self, *, site_id: str, days_back: int = 1) -> dict[str, Any]:
        result = run_weather_fetch(store=self.feather_store, site_id=site_id, days_back=days_back)
        return {"rows": result.rows, "source": result.source}

    def ingest_onboard(self, *, site_id: str) -> dict[str, Any]:
        result = run_onboard_scrape(store=self.feather_store, site_id=site_id)
        return {"rows": result.rows, "source": "onboard"}

    def load_source_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.connector.read_frame(source=source, site_id=site_id)

    def purge_timeseries(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        return self.feather_store.purge(source=source, site_id=site_id)

    def _upsert_point_for_metric(
        self,
        *,
        model: dict[str, Any],
        site_id: str,
        metric: str,
        source: str,
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
            md["external_ref"] = f"feather://{source}/{site_id}/{metric}"
            md["source"] = source
            existing["metadata"] = md
            return
        model["points"].append(
            {
                "id": self.model_service.store.id_str(),
                "site_id": site_id,
                "equipment_id": None,
                "external_id": metric,
                "brick_type": "Point",
                "fdd_input": None,
                "unit": None,
                "metadata": {
                    "external_ref": f"feather://{source}/{site_id}/{metric}",
                    "source": source,
                },
            }
        )

