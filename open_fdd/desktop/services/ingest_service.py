from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.desktop.drivers.bacnet_driver import run_bacnet_scrape
from open_fdd.desktop.drivers.onboard_driver import run_onboard_scrape
from open_fdd.desktop.drivers.weather_driver import run_weather_fetch
from open_fdd.desktop.services.ml_service import MLService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.time_utils import infer_timestamp_column, parse_timestamp_series
from open_fdd.desktop.services.timeseries_merge import (
    DEFAULT_SITE_DRIVER_SOURCES,
    merge_site_frames_on_timestamp,
)
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

    def ingest_bacnet(
        self,
        *,
        site_id: str,
        server_url: str,
        api_key: str = "",
    ) -> dict[str, Any]:
        model = self.model_service.load()
        result = run_bacnet_scrape(
            store=self.connector,
            model=model,
            site_id=site_id,
            server_url=server_url,
            api_key=api_key,
        )
        if not result.success:
            return {
                "rows": result.rows,
                "source": result.source,
                "success": False,
                "error": result.error or "BACnet ingest failed.",
                "devices_polled": result.devices_polled,
                "points_polled": result.points_polled,
            }
        metrics = [str(m) for m in (result.metrics or [])]
        storage_ref = str(result.storage_ref or "")
        with self.model_service.transaction() as model_tx:
            for metric in metrics:
                md = (result.point_metadata or {}).get(metric, {})
                self._upsert_point_for_metric(
                    model=model_tx,
                    site_id=site_id,
                    metric=metric,
                    source=result.source,
                    storage_ref=storage_ref,
                    brick_type_override=str(md.get("brick_type") or "Point"),
                    fdd_input_override=(str(md.get("fdd_input")) if md.get("fdd_input") is not None else None),
                    unit_override=(str(md.get("unit")) if md.get("unit") is not None else None),
                )
        return {
            "rows": result.rows,
            "source": result.source,
            "success": True,
            "devices_polled": result.devices_polled,
            "points_polled": result.points_polled,
            "warning": result.error,
        }

    def load_source_frame(self, *, source: str, site_id: str) -> pd.DataFrame:
        return self.connector.read_frame(source=source, site_id=site_id)

    def load_source_frame_window(
        self,
        *,
        source: str,
        site_id: str,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> pd.DataFrame:
        frame = self.load_source_frame(source=source, site_id=site_id)
        if frame.empty:
            return frame
        ts_col = infer_timestamp_column(frame)
        try:
            parsed = parse_timestamp_series(frame, timestamp_col=ts_col, min_valid_ratio=0.05)
        except ValueError:
            return frame.iloc[0:0].copy()
        out = frame[parsed.notna()].copy()
        out[ts_col] = parsed[parsed.notna()]
        if start_ts:
            start = pd.to_datetime(start_ts, errors="raise", utc=True)
            out = out[out[ts_col] >= start]
        if end_ts:
            end = pd.to_datetime(end_ts, errors="raise", utc=True)
            out = out[out[ts_col] <= end]
        return out.sort_values(ts_col).reset_index(drop=True)

    def load_merged_sources_frame_window(
        self,
        *,
        site_id: str,
        sources: list[str],
        start_ts: str | None = None,
        end_ts: str | None = None,
        join_how: str = "outer",
    ) -> tuple[pd.DataFrame, list[str]]:
        """
        Load each driver ``source`` for ``site_id`` (same optional time window as
        :meth:`load_source_frame_window`), then merge on ``timestamp``.

        Returns the merged frame and the list of driver tags that contributed at least
        one row (subset of ``sources``, order preserved).

        When only one source has rows, column names are unchanged. When two or more
        contribute rows, non-timestamp columns become ``<metric>_<source>`` to avoid
        collisions across BACnet / CSV / weather / onboard / future drivers.
        """
        cleaned = [str(s).strip() for s in sources if str(s).strip()]
        if not cleaned:
            return pd.DataFrame(), []
        parts: list[tuple[str, pd.DataFrame]] = []
        for src in cleaned:
            fr = self.load_source_frame_window(
                site_id=site_id,
                source=src,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            parts.append((src, fr))
        return merge_site_frames_on_timestamp(parts, join_how=join_how)

    @staticmethod
    def default_merge_driver_order() -> tuple[str, ...]:
        """Built-in driver source tags, in a stable merge order (override via explicit ``sources``)."""
        return DEFAULT_SITE_DRIVER_SOURCES

    def source_time_bounds(self, *, source: str, site_id: str) -> dict[str, Any]:
        frame = self.load_source_frame(source=source, site_id=site_id)
        if frame.empty:
            return {"rows": 0, "timestamp_col": None, "start": None, "end": None}
        ts_col = infer_timestamp_column(frame)
        try:
            parsed = parse_timestamp_series(frame, timestamp_col=ts_col, min_valid_ratio=0.05)
        except ValueError:
            return {"rows": len(frame.index), "timestamp_col": ts_col, "start": None, "end": None}
        valid = parsed[parsed.notna()]
        if valid.empty:
            return {"rows": len(frame.index), "timestamp_col": ts_col, "start": None, "end": None}
        return {
            "rows": len(frame.index),
            "timestamp_col": ts_col,
            "start": valid.min().isoformat(),
            "end": valid.max().isoformat(),
        }

    def purge_timeseries(self, *, source: str | None = None, site_id: str | None = None) -> dict[str, int]:
        return self.connector.purge(source=source, site_id=site_id)

    def train_ml_baseline(
        self,
        *,
        site_id: str,
        source: str,
        target_col: str,
        feature_cols: list[str] | None = None,
        lag_cols: list[str] | None = None,
        residual_quantile: float = 0.95,
        rule_flag_col: str | None = None,
        output_source: str | None = None,
    ) -> dict[str, Any]:
        ml = MLService(connector=self.connector)
        result = ml.train_baseline(
            site_id=site_id,
            source=source,
            target_col=target_col,
            feature_cols=feature_cols,
            lag_cols=lag_cols,
            residual_quantile=residual_quantile,
            rule_flag_col=rule_flag_col,
            output_source=output_source,
        )
        return {
            "rows_train": result.rows_train,
            "rows_test": result.rows_test,
            "rows_scored": result.rows_scored,
            "model_name": result.model_name,
            "mae": result.mae,
            "rmse": result.rmse,
            "r2": result.r2,
            "residual_threshold": result.residual_threshold,
            "output_source": result.output_source,
            "storage_ref": result.storage_ref,
            "overlap_with_rule_flag": result.overlap_with_rule_flag,
        }

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

