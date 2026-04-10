"""
Modbus TCP scrape via diy-bacnet-server REST (POST /modbus/read_registers).

Points with non-null ``modbus_config`` jsonb and ``polling`` true are read each cycle.
Registers that share the same host/port/unit_id are batched in one HTTP request.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from openfdd_stack.platform.bacnet_gateway_auth import bacnet_gateway_request_headers
from openfdd_stack.platform.config import get_platform_settings
from openfdd_stack.platform.database import get_conn
from openfdd_stack.platform.modbus_point_config import normalize_modbus_config
from openfdd_stack.platform.site_resolver import resolve_site_uuid

logger = logging.getLogger("open_fdd.modbus")


def _reading_to_float(reading: dict[str, Any]) -> Optional[float]:
    dec = reading.get("decoded")
    if dec is not None and isinstance(dec, (int, float)):
        return float(dec)
    words = reading.get("words")
    if isinstance(words, list) and words:
        try:
            return float(words[0])
        except (TypeError, ValueError):
            return None
    return None


def get_modbus_points_from_data_model(site_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Load points with modbus_config set and polling enabled (configs normalized)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id:
                cur.execute(
                    """
                    SELECT p.id, p.site_id, p.external_id, p.modbus_config
                    FROM points p
                    JOIN sites s ON s.id = p.site_id
                    WHERE p.modbus_config IS NOT NULL
                      AND jsonb_typeof(p.modbus_config) = 'object'
                      AND COALESCE(p.polling, true) = true
                      AND (s.id::text = %s OR s.name = %s)
                    ORDER BY p.site_id, p.external_id
                    """,
                    (site_id, site_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, site_id, external_id, modbus_config
                    FROM points
                    WHERE modbus_config IS NOT NULL
                      AND jsonb_typeof(modbus_config) = 'object'
                      AND COALESCE(polling, true) = true
                    ORDER BY site_id, external_id
                    """
                )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r["modbus_config"]
        if not isinstance(raw, dict):
            continue
        cfg = normalize_modbus_config(raw)
        if cfg is None:
            logger.warning(
                "Skipping point %s: modbus_config failed validation/normalization",
                r.get("external_id") or r.get("id"),
            )
            continue
        out.append(
            {
                "id": r["id"],
                "site_id": str(r["site_id"]),
                "external_id": (r["external_id"] or "").strip(),
                "modbus_config": cfg,
            }
        )
    return out


def _group_key(cfg: dict[str, Any]) -> tuple[str, int, int, float]:
    host = (cfg.get("host") or "").strip()
    port = int(cfg["port"])
    unit = int(cfg["unit_id"])
    timeout = float(cfg["timeout"])
    return (host, port, unit, timeout)


def _register_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    """Single register entry for diy-bacnet-server body."""
    addr = int(cfg["address"])
    count = int(cfg["count"])
    fn = str(cfg["function"])
    reg: dict[str, Any] = {
        "address": addr,
        "count": count,
        "function": fn,
    }
    if cfg.get("decode") is not None:
        reg["decode"] = cfg["decode"]
    if cfg.get("scale") is not None:
        reg["scale"] = cfg["scale"]
    if cfg.get("offset") is not None:
        reg["offset"] = cfg["offset"]
    if cfg.get("label"):
        reg["label"] = str(cfg["label"])
    return reg


def run_modbus_scrape_data_model(
    site_id: Optional[str] = None,
    server_url: Optional[str] = None,
) -> dict[str, Any]:
    """
    Poll Modbus-backed points. Returns {rows_inserted, errors}.
    """
    settings = get_platform_settings()
    if not settings.bacnet_scrape_enabled:
        logger.info("Modbus scrape skipped (bacnet_scrape_enabled false)")
        return {"rows_inserted": 0, "errors": ["Scrape disabled"]}

    url = (server_url or settings.bacnet_server_url or "").strip().rstrip("/")
    if not url:
        return {"rows_inserted": 0, "errors": ["OFDD_BACNET_SERVER_URL not set"]}

    points_list = get_modbus_points_from_data_model(site_id)
    if not points_list:
        return {"rows_inserted": 0, "errors": []}

    groups: dict[tuple[str, int, int], list[tuple[dict, dict]]] = defaultdict(list)
    timeouts: dict[tuple[str, int, int], float] = {}
    for row in points_list:
        cfg = row["modbus_config"]
        h, p, u, tmo = _group_key(cfg)
        gk = (h, p, u)
        groups[gk].append((row, cfg))
        timeouts[gk] = max(timeouts.get(gk, 0.0), tmo)

    ts = datetime.now(timezone.utc)
    errors: list[str] = []
    pending_inserts: list[tuple[str, str, float]] = []

    for gk, pairs in groups.items():
        h, p, u = gk
        timeout = min(120.0, max(5.0, timeouts.get(gk, 5.0)))
        registers = [_register_payload(cfg) for _, cfg in pairs]
        body = {
            "host": h,
            "port": p,
            "unit_id": u,
            "timeout": timeout,
            "registers": registers,
        }
        try:
            r = httpx.post(
                f"{url}/modbus/read_registers",
                json=body,
                timeout=timeout + 15.0,
                headers=bacnet_gateway_request_headers(),
            )
            if not r.is_success:
                errors.append(f"{h}:{p} unit {u}: HTTP {r.status_code}")
                continue
            data = r.json()
        except Exception as e:
            errors.append(f"{h}:{p} unit {u}: {e}")
            continue

        readings = data.get("readings") if isinstance(data, dict) else None
        if not isinstance(readings, list) or len(readings) != len(pairs):
            errors.append(
                f"{h}:{p} unit {u}: unexpected readings count "
                f"(got {len(readings) if isinstance(readings, list) else 0}, want {len(pairs)})"
            )
            continue

        for i, (row, _cfg) in enumerate(pairs):
            rid = readings[i]
            if not isinstance(rid, dict) or not rid.get("success"):
                errors.append(
                    f"Point {row['external_id']}: {rid.get('error') if isinstance(rid, dict) else 'read failed'}"
                )
                continue
            val = _reading_to_float(rid)
            if val is None:
                errors.append(f"Point {row['external_id']}: no numeric value")
                continue
            site_uuid = resolve_site_uuid(row["site_id"])
            if not site_uuid:
                errors.append(f"Point {row['external_id']}: unknown site")
                continue
            pending_inserts.append((str(site_uuid), str(row["id"]), val))

    rows_inserted = 0
    if pending_inserts:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for site_uuid_str, point_id_str, val in pending_inserts:
                    cur.execute(
                        """
                        INSERT INTO timeseries_readings (ts, site_id, point_id, value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (ts, site_uuid_str, point_id_str, val),
                    )
                    rows_inserted += 1
            conn.commit()

    logger.info(
        "Modbus scrape: %d readings written, %d errors, ts=%s",
        rows_inserted,
        len(errors),
        ts.isoformat(),
    )
    return {"rows_inserted": rows_inserted, "errors": errors}
