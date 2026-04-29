from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd


class FrameStore(Protocol):
    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str: ...


@dataclass
class BacnetScrapeResult:
    rows: int
    source: str = "bacnet"
    metrics: list[str] | None = None
    storage_ref: str | None = None
    point_metadata: dict[str, dict[str, str | None]] | None = None
    success: bool = True
    error: str | None = None
    devices_polled: int = 0
    points_polled: int = 0


def _to_device_instance(raw: str) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if "," in text:
        text = text.split(",")[-1].strip()
    try:
        return int(text)
    except ValueError:
        return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"active", "true", "1", "on", "closed"}:
        return 1.0
    if text in {"inactive", "false", "0", "off", "open"}:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_brick_type(object_identifier: str) -> str:
    oid = str(object_identifier or "").split(",")[0].strip().lower()
    if oid.startswith("analog-"):
        return "Sensor"
    if oid.startswith("binary-") or oid.startswith("multi-state-"):
        return "Status"
    return "Point"


def run_bacnet_scrape(
    *,
    store: FrameStore,
    model: dict[str, Any],
    site_id: str,
    server_url: str,
    api_key: str = "",
) -> BacnetScrapeResult:
    points = [
        p
        for p in model.get("points", [])
        if str(p.get("site_id")) == str(site_id)
        and str(p.get("external_id") or "").strip()
        and str(p.get("bacnet_device_id") or "").strip()
        and str(p.get("object_identifier") or "").strip()
        and bool(p.get("polling", True))
    ]
    if not points:
        return BacnetScrapeResult(
            rows=0,
            source="bacnet",
            metrics=[],
            storage_ref=None,
            success=False,
            error="No BACnet points with polling=true found in model for site.",
            devices_polled=0,
            points_polled=0,
        )

    by_device: dict[int, list[dict[str, Any]]] = {}
    for point in points:
        did = _to_device_instance(str(point.get("bacnet_device_id") or ""))
        if did is None:
            continue
        by_device.setdefault(did, []).append(point)

    if not by_device:
        return BacnetScrapeResult(
            rows=0,
            source="bacnet",
            metrics=[],
            storage_ref=None,
            success=False,
            error="Model points are missing valid bacnet_device_id values.",
            devices_polled=0,
            points_polled=0,
        )

    base = str(server_url or "").strip().rstrip("/")
    if not base:
        return BacnetScrapeResult(
            rows=0,
            source="bacnet",
            metrics=[],
            storage_ref=None,
            success=False,
            error="Missing BACnet server URL.",
            devices_polled=0,
            points_polled=0,
        )
    parsed_base = urllib.parse.urlparse(base)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        return BacnetScrapeResult(
            rows=0,
            source="bacnet",
            metrics=[],
            storage_ref=None,
            success=False,
            error=f"Invalid or unsupported server URL scheme: {server_url}",
            devices_polled=0,
            points_polled=0,
        )

    headers = {"Content-Type": "application/json", "accept": "application/json"}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    now_iso = datetime.now(timezone.utc).isoformat()
    row: dict[str, object] = {"timestamp": now_iso}
    point_meta: dict[str, dict[str, str | None]] = {}
    errors: list[str] = []

    for device_instance, device_points in by_device.items():
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "client_read_multiple",
            "params": {
                "request": {
                    "device_instance": device_instance,
                    "requests": [
                        {
                            "object_identifier": str(p.get("object_identifier") or ""),
                            "property_identifier": "present-value",
                        }
                        for p in device_points
                    ],
                }
            },
        }
        req = urllib.request.Request(
            f"{base}/client_read_multiple",
            method="POST",
            headers=headers,
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append(f"device,{device_instance}: {exc}")
            continue

        if isinstance(body, dict) and body.get("error"):
            errors.append(f"device,{device_instance}: {body['error']}")
            continue
        result = body.get("result", {}) if isinstance(body, dict) else {}
        data = result.get("data", {}) if isinstance(result, dict) else {}
        values = data.get("results", []) if isinstance(data, dict) else []
        for idx, item in enumerate(values):
            if idx >= len(device_points):
                continue
            point = device_points[idx]
            external_id = str(point.get("external_id") or "").strip()
            if not external_id:
                continue
            if external_id in row or external_id in point_meta:
                namespaced = f"{external_id}_{device_instance}_{idx}"
                errors.append(
                    f"Duplicate external_id '{external_id}' for device,{device_instance} object={point.get('object_identifier')}; using '{namespaced}'."
                )
                external_id = namespaced
            raw_val = item.get("value") if isinstance(item, dict) else None
            val = _to_float(raw_val)
            if val is None:
                continue
            row[external_id] = val
            point_meta[external_id] = {
                "brick_type": str(point.get("brick_type") or _default_brick_type(str(point.get("object_identifier") or ""))),
                "fdd_input": str(point.get("fdd_input")) if point.get("fdd_input") is not None else None,
                "unit": str(point.get("unit")) if point.get("unit") is not None else None,
            }

    metric_cols = [str(c) for c in row.keys() if str(c) != "timestamp"]
    if not metric_cols:
        return BacnetScrapeResult(
            rows=0,
            source="bacnet",
            metrics=[],
            storage_ref=None,
            success=False,
            error=("; ".join(errors) if errors else "No BACnet values returned from gateway."),
            devices_polled=len(by_device),
            points_polled=sum(len(v) for v in by_device.values()),
        )

    frame = pd.DataFrame([row])
    storage_ref = store.write_frame(source="bacnet", site_id=site_id, frame=frame)
    return BacnetScrapeResult(
        rows=len(frame.index),
        source="bacnet",
        metrics=metric_cols,
        storage_ref=storage_ref,
        point_metadata=point_meta,
        success=True,
        error=("; ".join(errors) if errors else None),
        devices_polled=len(by_device),
        points_polled=sum(len(v) for v in by_device.values()),
    )
