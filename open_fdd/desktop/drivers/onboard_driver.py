from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Protocol
import urllib.error
import urllib.request

import pandas as pd

class FrameStore(Protocol):
    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...


@dataclass
class OnboardScrapeResult:
    rows: int
    source: str = "onboard"
    metrics: list[str] | None = None
    storage_ref: str | None = None
    point_metadata: dict[str, dict[str, str | None]] | None = None


def run_onboard_scrape(*, store: FrameStore, site_id: str) -> OnboardScrapeResult:
    base_url = os.getenv("OFDD_ONBOARD_API_BASE_URL", "https://api.onboarddata.io").rstrip("/")
    api_key = os.getenv("OFDD_ONBOARD_API_KEY", "").strip()
    building_ids_raw = os.getenv("OFDD_ONBOARD_BUILDING_IDS", "").strip()
    lookback_hours = int(os.getenv("OFDD_ONBOARD_LOOKBACK_HOURS", "24"))

    if not api_key:
        now = datetime.now(timezone.utc)
        frame = pd.DataFrame({"timestamp": [now], "diagnostic_source": ["onboard"], "value": [1.0]})
        storage_ref = store.write_frame(source="onboard", site_id=site_id, frame=frame)
        return OnboardScrapeResult(rows=len(frame.index), source="onboard", metrics=["value"], storage_ref=storage_ref)

    def _request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> list[dict]:
        url = f"{base_url}{path}"
        headers = {"X-OB-Api": api_key, "Content-Type": "application/json"}
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body if isinstance(body, list) else []

    def _safe_token(value: object) -> str:
        token = str(value or "").strip().replace(" ", "_")
        return token or "metric"

    def _map_brick(name: str, units: str) -> tuple[str, str | None]:
        text = f"{name} {units}".lower()
        if "temp" in text:
            return ("Supply_Air_Temperature_Sensor", "sat")
        if "humid" in text or "rh" in text:
            return ("Relative_Humidity_Sensor", None)
        if "damper" in text:
            return ("Damper_Position_Command", "damper")
        if "fan" in text and ("speed" in text or "%" in text):
            return ("Fan_Speed_Command", "fan_speed")
        if "pressure" in text or "in/wc" in text:
            return ("Pressure_Sensor", None)
        return ("Point", None)

    building_filters = {item.strip() for item in building_ids_raw.split(",") if item.strip()}
    buildings = _request_json("/buildings")
    if building_filters:
        buildings = [
            b for b in buildings
            if str(b.get("id", "")).strip() in building_filters or str(b.get("name", "")).strip() in building_filters
        ]

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(1, lookback_hours))
    rows_by_ts: dict[str, dict[str, object]] = {}
    point_meta: dict[str, dict[str, str | None]] = {}

    for building in buildings:
        building_id = building.get("id")
        if building_id is None:
            continue
        try:
            points = _request_json(f"/buildings/{int(building_id)}/points")
        except urllib.error.URLError:
            continue
        point_ids = [int(p["id"]) for p in points if p.get("id") is not None]
        if not point_ids:
            continue
        query_rows = _request_json(
            "/query-v2",
            method="POST",
            payload={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "point_ids": point_ids,
            },
        )
        points_by_id = {int(p["id"]): p for p in points if p.get("id") is not None}
        for item in query_rows:
            point_id = item.get("point_id")
            if point_id is None:
                continue
            point = points_by_id.get(int(point_id), {})
            metric = _safe_token(point.get("topic") or point.get("name") or f"onboard_{point_id}")
            units = str(point.get("tagged_units") or point.get("units") or "")
            brick_type, fdd_input = _map_brick(metric, units)
            point_meta[metric] = {"brick_type": brick_type, "fdd_input": fdd_input, "unit": units or None}
            for sample in item.get("values", []) or []:
                if not isinstance(sample, list) or len(sample) < 2:
                    continue
                raw_ts = str(sample[0])
                if raw_ts.endswith("Z"):
                    raw_ts = raw_ts[:-1] + "+00:00"
                try:
                    ts = datetime.fromisoformat(raw_ts)
                except ValueError:
                    continue
                ts_iso = ts.astimezone(timezone.utc).isoformat()
                val_raw = sample[-1] if len(sample) >= 3 else sample[1]
                try:
                    val = float(val_raw)
                except (TypeError, ValueError):
                    continue
                row = rows_by_ts.setdefault(ts_iso, {"timestamp": ts_iso})
                row[metric] = val

    if not rows_by_ts:
        frame = pd.DataFrame({"timestamp": [end.isoformat()]})
    else:
        frame = pd.DataFrame(list(rows_by_ts.values())).sort_values("timestamp")
    storage_ref = store.write_frame(source="onboard", site_id=site_id, frame=frame)
    metrics = [str(c) for c in frame.columns if str(c) != "timestamp"]
    return OnboardScrapeResult(
        rows=len(frame.index),
        source="onboard",
        metrics=metrics,
        storage_ref=storage_ref,
        point_metadata=point_meta,
    )

