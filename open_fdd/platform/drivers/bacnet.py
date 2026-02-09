"""
BACnet driver: RPC-driven scrape via diy-bacnet-server.

Reads present-value from CSV config, writes to timeseries_readings.
Uses diy-bacnet-server JSON-RPC (client_read_property, client_read_multiple) only.

CSV format: device_id, object_identifier, object_type, object_instance, object_name, present_value, units
Requires: OFDD_BACNET_SERVER_URL (e.g. http://localhost:8080)
"""

from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from open_fdd.platform.database import get_conn
from open_fdd.platform.config import get_platform_settings

logger = logging.getLogger("open_fdd.bacnet")


from open_fdd.platform.drivers.bacnet_validate import validate_bacnet_csv


def _pv_to_float(pv) -> Optional[float]:
    """Convert BACnet present-value to float for timeseries. Binary -> 0/1."""
    if pv is None:
        return None
    if hasattr(pv, "__float__"):
        try:
            return float(pv)
        except (TypeError, ValueError):
            pass
    s = str(pv).lower().strip()
    if s in ("active", "true", "1", "closed"):
        return 1.0
    if s in ("inactive", "false", "0", "open"):
        return 0.0
    try:
        return float(pv)
    except (TypeError, ValueError):
        return None


async def _scrape_via_rpc(
    csv_path: Path,
    site_id: str,
    config_rows: list[tuple[int, dict]],
    by_device: dict[str, list[tuple[int, dict]]],
) -> dict:
    """Scrape via diy-bacnet-server JSON-RPC API."""
    import httpx

    settings = get_platform_settings()
    url = (settings.bacnet_server_url or "").rstrip("/")
    if not url:
        return {
            "rows_inserted": 0,
            "points_created": 0,
            "errors": ["OFDD_BACNET_SERVER_URL not set"],
        }

    rpc_base = url.rstrip("/")
    errors: list[str] = []
    readings: list[tuple[datetime, str, str, float]] = []
    ts = datetime.utcnow()

    site_uuid = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM sites WHERE id::text = %s OR name = %s",
                    (site_id, site_id),
                )
                row = cur.fetchone()
                if row:
                    site_uuid = row["id"]
                else:
                    cur.execute(
                        "INSERT INTO sites (name) VALUES (%s) RETURNING id", (site_id,)
                    )
                    site_uuid = cur.fetchone()["id"]
                    conn.commit()
                    logger.info("Created site: %s", site_id)
    except Exception as db_err:
        logger.error("DB error: %s", db_err)
        return {"rows_inserted": 0, "points_created": 0, "errors": [str(db_err)]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Verify diy-bacnet-server is reachable (path = /method for fastapi-jsonrpc)
        try:
            hello = await client.post(
                f"{rpc_base}/server_hello",
                json={
                    "jsonrpc": "2.0",
                    "id": "0",
                    "method": "server_hello",
                    "params": {},
                },
            )
            if hello.status_code == 200:
                logger.info("diy-bacnet-server reachable: %s", url)
            else:
                logger.warning("diy-bacnet-server returned %s", hello.status_code)
        except Exception as e:
            logger.warning("diy-bacnet-server unreachable: %s", e)

        for device_id_str, points in by_device.items():
            try:
                device_instance = int(device_id_str.split(",")[-1].strip())
            except (ValueError, IndexError):
                errors.append(f"Invalid device_id: {device_id_str}")
                continue

            logger.info(
                "BACnet device %s: reading %d points (RPC)", device_id_str, len(points)
            )
            point_specs: list[tuple[str, int, str]] = []
            for line_num, r in points:
                oid_str = r.get("object_identifier", "").strip().strip('"')
                obj_name = (r.get("object_name") or "").strip() or oid_str.replace(
                    ",", "_"
                )
                point_specs.append((oid_str, line_num, obj_name))

            device_readings: list[tuple[str, float]] = []

            if len(point_specs) > 1:
                req = {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "client_read_multiple",
                    "params": {
                        "request": {
                            "device_instance": device_instance,
                            "requests": [
                                {
                                    "object_identifier": oid,
                                    "property_identifier": "present-value",
                                }
                                for oid, _, _ in point_specs
                            ],
                        }
                    },
                }
                try:
                    resp = await client.post(
                        f"{rpc_base}/client_read_multiple", json=req
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if "error" in data:
                        raise RuntimeError(
                            data["error"].get("message", str(data["error"]))
                        )
                    result = data.get("result", {})
                    if (
                        isinstance(result, dict)
                        and result.get("success")
                        and result.get("data")
                    ):
                        rpm_results = result["data"].get("results", [])
                        oid_to_spec = {s[0]: (s[1], s[2]) for s in point_specs}
                        for idx, item in enumerate(rpm_results):
                            oid_str = str(item.get("object_identifier", "")).strip()
                            line_num, obj_name = oid_to_spec.get(
                                oid_str,
                                (
                                    (point_specs[idx][1], point_specs[idx][2])
                                    if idx < len(point_specs)
                                    else (0, oid_str)
                                ),
                            )
                            val_raw = item.get("value")
                            if isinstance(val_raw, str) and val_raw.startswith(
                                "Error:"
                            ):
                                errors.append(f"Line {line_num} {oid_str}: {val_raw}")
                            else:
                                val = _pv_to_float(val_raw)
                                if val is not None:
                                    device_readings.append((obj_name, val))
                        logger.info(
                            "BACnet RPC client_read_multiple OK for %s: %d values",
                            device_id_str,
                            len(device_readings),
                        )
                except Exception as e:
                    logger.warning(
                        "BACnet RPC client_read_multiple failed for %s (%s), falling back to client_read_property",
                        device_id_str,
                        e,
                    )

            if not device_readings and point_specs:
                for oid_str, line_num, obj_name in point_specs:
                    req = {
                        "jsonrpc": "2.0",
                        "id": str(line_num),
                        "method": "client_read_property",
                        "params": {
                            "request": {
                                "device_instance": device_instance,
                                "object_identifier": oid_str,
                                "property_identifier": "present-value",
                            }
                        },
                    }
                    try:
                        resp = await client.post(
                            f"{rpc_base}/client_read_property", json=req
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        if "error" in data:
                            err_msg = data["error"].get("message", str(data["error"]))
                            errors.append(f"Line {line_num} {oid_str}: {err_msg}")
                            continue
                        result = data.get("result", {})
                        if isinstance(result, dict) and "present-value" in result:
                            val = _pv_to_float(result["present-value"])
                            if val is not None:
                                device_readings.append((obj_name, val))
                    except Exception as e:
                        errors.append(f"Line {line_num} {oid_str}: {e}")

            for obj_name, val in device_readings:
                readings.append((ts, str(site_uuid), obj_name, val))

    rows_inserted = 0
    points_created = 0
    if readings:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for ts_r, sid, ext_id, val in readings:
                    cur.execute(
                        """
                        INSERT INTO points (site_id, external_id) VALUES (%s, %s)
                        ON CONFLICT (site_id, external_id) DO UPDATE SET external_id = EXCLUDED.external_id
                        RETURNING id
                        """,
                        (site_uuid, ext_id),
                    )
                    pid = cur.fetchone()["id"]
                    cur.execute(
                        """
                        INSERT INTO timeseries_readings (ts, site_id, point_id, value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (ts_r, sid, pid, val),
                    )
                    rows_inserted += 1
                points_created = len(set(r[2] for r in readings))
                conn.commit()

    if errors:
        for e in errors:
            logger.warning("BACnet scrape error: %s", e)

    logger.info(
        "BACnet scrape OK (RPC): %d readings written, %d points, ts=%s",
        rows_inserted,
        points_created,
        ts.isoformat(),
    )
    return {
        "rows_inserted": rows_inserted,
        "points_created": points_created,
        "errors": errors,
    }


async def scrape_bacnet_from_csv(
    csv_path: Path,
    site_id: str,
    equipment_id: str,
) -> dict:
    """
    Read present-value for each row in CSV, insert into timeseries_readings.
    Returns {rows_inserted, points_created, errors}.
    """
    settings = get_platform_settings()
    if not settings.bacnet_scrape_enabled:
        logger.info("BACnet scrape disabled (OFDD_BACNET_SCRAPE_ENABLED=false)")
        return {"rows_inserted": 0, "points_created": 0, "errors": ["Scrape disabled"]}

    errors = validate_bacnet_csv(csv_path)
    if errors:
        for line_num, msg in errors:
            logger.error("BACnet CSV validation: %s", msg)
        return {
            "rows_inserted": 0,
            "points_created": 0,
            "errors": [msg for _, msg in errors],
        }

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        config_rows = [(i + 2, r) for i, r in enumerate(reader)]

    if not config_rows:
        logger.warning("BACnet CSV has no data rows")
        return {"rows_inserted": 0, "points_created": 0, "errors": []}

    by_device: dict[str, list[tuple[int, dict]]] = {}
    for line_num, r in config_rows:
        did = r.get("device_id", "").strip().strip('"')
        if did not in by_device:
            by_device[did] = []
        by_device[did].append((line_num, r))

    # RPC-only: require diy-bacnet-server
    if not settings.bacnet_server_url:
        logger.error(
            "OFDD_BACNET_SERVER_URL required. Start diy-bacnet-server (e.g. docker compose) and set it."
        )
        return {
            "rows_inserted": 0,
            "points_created": 0,
            "errors": [
                "Set OFDD_BACNET_SERVER_URL (e.g. http://localhost:8080) for RPC-driven scrape"
            ],
        }

    logger.info("BACnet scrape via RPC: %s", settings.bacnet_server_url)
    return await _scrape_via_rpc(csv_path, site_id, config_rows, by_device)


def run_bacnet_scrape(
    csv_path: Path,
    site_id: str = "default",
    equipment_id: str = "bacnet",
) -> dict:
    """Synchronous wrapper for scrape_bacnet_from_csv."""
    return asyncio.run(scrape_bacnet_from_csv(csv_path, site_id, equipment_id))
