from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.desktop.drivers.csv_driver import ingest_csv_to_feather
from open_fdd.desktop.drivers.onboard_driver import run_onboard_scrape
from open_fdd.desktop.drivers.weather_driver import run_weather_fetch
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.storage.feather_store import FeatherStore


@dataclass
class IngestService:
    model_service: ModelService = field(default_factory=ModelService)
    feather_store: FeatherStore = field(default_factory=FeatherStore)

    def ingest_csv(self, *, csv_path: str | Path, site_id: str, source: str = "csv") -> dict[str, Any]:
        result = ingest_csv_to_feather(csv_path=csv_path, source=source, site_id=site_id, store=self.feather_store)
        for metric in result.metric_columns:
            self._ensure_point_for_metric(site_id=site_id, metric=metric, source=source)
        return {"rows": result.rows, "feather_path": str(result.file_path), "metrics": result.metric_columns}

    def ingest_weather(self, *, site_id: str, days_back: int = 1) -> dict[str, Any]:
        result = run_weather_fetch(store=self.feather_store, site_id=site_id, days_back=days_back)
        return {"rows": result.rows, "source": result.source}

    def ingest_onboard(self, *, site_id: str) -> dict[str, Any]:
        result = run_onboard_scrape(store=self.feather_store, site_id=site_id)
        return {"rows": result.rows, "source": "onboard"}

    def load_source_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.feather_store.read_site_frames(source=source, site_id=site_id)

    def _ensure_point_for_metric(self, *, site_id: str, metric: str, source: str) -> None:
        model = self.model_service.load()
        existing = next((p for p in model["points"] if p.get("site_id") == site_id and p.get("external_id") == metric), None)
        if existing:
            md = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
            md["external_ref"] = f"feather://{source}/{site_id}/{metric}"
            existing["metadata"] = md
            self.model_service.store.save(model)
            return
        self.model_service.create_point(
            site_id=site_id,
            equipment_id=None,
            external_id=metric,
            brick_type="Point",
            metadata={"external_ref": f"feather://{source}/{site_id}/{metric}"},
        )

