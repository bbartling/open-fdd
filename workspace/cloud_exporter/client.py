"""HTTP client — poll bridge internal APIs and POST export payload."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import ExporterConfig

_log = logging.getLogger("openfdd.cloud_exporter")


def _auth_headers(cfg: ExporterConfig) -> dict[str, str]:
    if not cfg.token:
        return {}
    return {"Authorization": f"Bearer {cfg.token}"}


def _get_json(client: httpx.Client, path: str, cfg: ExporterConfig) -> dict[str, Any]:
    url = f"{cfg.bridge_base_url.rstrip('/')}{path}"
    try:
        resp = client.get(url, headers=_auth_headers(cfg), timeout=cfg.timeout_seconds)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else {"data": data}
    except httpx.HTTPError as exc:
        _log.warning("bridge GET %s failed: %s", path, exc)
    return {}


def build_payload(client: httpx.Client, cfg: ExporterConfig) -> dict[str, Any]:
    health = _get_json(client, "/health", cfg)
    payload: dict[str, Any] = {
        "source": "open-fdd",
        "site_id": cfg.site_id or health.get("site_id") or "unknown",
        "building_id": health.get("building_id") or "",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "bridge_base_url": "redacted/local",
        "health": health,
        "readings": [],
        "faults": [],
        "model_summary": {},
        "metadata": {
            "exporter_version": "0.1.0",
            "dry_run": cfg.dry_run,
            "config": cfg.redacted(),
        },
    }

    if cfg.include_readings:
        readings = _get_json(client, f"/api/timeseries/latest?limit={cfg.max_points}", cfg)
        payload["readings"] = readings.get("points") or readings.get("readings") or readings

    if cfg.include_faults:
        faults = _get_json(client, "/api/fdd/summary", cfg)
        payload["faults"] = faults.get("faults") or faults.get("active") or faults

    if cfg.include_model_summary:
        model = _get_json(client, "/api/model/health", cfg)
        payload["model_summary"] = model

    bacnet = _get_json(client, "/api/bacnet/commission/status", cfg)
    if bacnet:
        payload["bacnet_status"] = {
            k: bacnet.get(k)
            for k in ("bacnet_bind", "enabled_points", "samples")
            if k in bacnet
        }

    return payload


def post_payload(client: httpx.Client, cfg: ExporterConfig, payload: dict[str, Any]) -> dict[str, Any]:
    if not cfg.export_endpoint:
        return {"ok": False, "error": "OPENFDD_EXPORT_ENDPOINT not configured"}
    if cfg.dry_run:
        _log.info(
            "dry-run export site=%s readings=%s faults=%s",
            payload.get("site_id"),
            len(payload.get("readings") or []),
            len(payload.get("faults") or []) if isinstance(payload.get("faults"), list) else "n/a",
        )
        return {"ok": True, "dry_run": True}

    headers = {"Content-Type": "application/json", **_auth_headers(cfg)}
    try:
        resp = client.post(
            cfg.export_endpoint,
            json=payload,
            headers=headers,
            timeout=cfg.timeout_seconds,
        )
        return {"ok": 200 <= resp.status_code < 300, "status_code": resp.status_code}
    except httpx.HTTPError as exc:
        _log.warning("export POST failed: %s", exc)
        return {"ok": False, "error": str(exc)}
