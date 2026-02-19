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
from open_fdd.platform.site_resolver import resolve_site_uuid

logger = logging.getLogger("open_fdd.bacnet")


from open_fdd.platform.drivers.bacnet_validate import validate_bacnet_csv


def get_bacnet_points_from_data_model(
    site_id: Optional[str] = None,
) -> list[dict]:
    """
    Load points that have BACnet addressing (bacnet_device_id, object_identifier) from the data model.
    Returns list of dicts: site_id (uuid str), external_id, bacnet_device_id, object_identifier, object_name, device_id (for grouping).
    If site_id is set, filter by that site (by name or uuid); otherwise all sites.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id:
                cur.execute(
                    """
                    SELECT p.id, p.site_id, p.external_id, p.bacnet_device_id, p.object_identifier, p.object_name
                    FROM points p
                    JOIN sites s ON s.id = p.site_id
                    WHERE p.bacnet_device_id IS NOT NULL AND p.object_identifier IS NOT NULL
                      AND (s.id::text = %s OR s.name = %s)
                      AND COALESCE(p.polling, true) = true
                    ORDER BY p.bacnet_device_id, p.object_identifier
                    """,
                    (site_id, site_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, site_id, external_id, bacnet_device_id, object_identifier, object_name
                    FROM points
                    WHERE bacnet_device_id IS NOT NULL AND object_identifier IS NOT NULL
                      AND COALESCE(polling, true) = true
                    ORDER BY site_id, bacnet_device_id, object_identifier
                    """,
                )
            rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        did = (r["bacnet_device_id"] or "").strip()
        if "," not in did:
            did = f"device,{did}" if did else ""
        out.append(
            {
                "site_id": str(r["site_id"]),
                "external_id": (r["external_id"] or "").strip(),
                "bacnet_device_id": (r["bacnet_device_id"] or "").strip(),
                "object_identifier": (r["object_identifier"] or "").strip(),
                "object_name": (r["object_name"] or "").strip()
                or (r["object_identifier"] or "").strip(),
                "device_id": did,
            }
        )
    return out


def _pv_to_float(pv) -> Optional[float]:
    """Convert BACnet present-value to float for timeseries. Binary -> 0/1."""
    if pv is None:
        return None
    if hasattr(pv, "__float__"):
        try:
            return float(pv)
        except TypeError:
            pass
        except ValueError:
            pass
    s = str(pv).lower().strip()
    if s in ("active", "true", "1", "closed"):
        return 1.0
    if s in ("inactive", "false", "0", "open"):
        return 0.0
    try:
        return float(pv)
    except TypeError:
        return None
    except ValueError:
        return None


def _site_uuid_cache() -> dict[str, str]:
    """Per-invocation cache for resolve_site_uuid (used when rows have per-row site_id)."""
    return {}


async def _scrape_via_rpc(
    csv_path: Optional[Path],
    site_id: str,
    config_rows: list[tuple[int, dict]],
    by_device: dict[str, list[tuple[int, dict]]],
    server_url: Optional[str] = None,
) -> dict:
    """Scrape via diy-bacnet-server JSON-RPC API. server_url overrides settings when set.
    When csv_path is None, config rows may include site_id and external_id for per-reading site (data-model path).
    """
    import httpx

    settings = get_platform_settings()
    url = (server_url or settings.bacnet_server_url or "").rstrip("/")
    if not url:
        return {
            "rows_inserted": 0,
            "points_created": 0,
            "errors": ["OFDD_BACNET_SERVER_URL not set"],
        }

    rpc_base = url.rstrip("/")
    errors: list[str] = []
    # (ts, site_uuid, external_id, value, bacnet_device_id, object_identifier)
    readings: list[tuple[datetime, str, str, float, str, str]] = []
    ts = datetime.utcnow()
    site_uuid_cache = _site_uuid_cache()

    def resolve_cached(sid: str) -> Optional[str]:
        if not sid:
            return None
        if sid not in site_uuid_cache:
            site_uuid_cache[sid] = resolve_site_uuid(sid)
        return site_uuid_cache[sid]

    site_uuid: Optional[str] = None
    if not any(r.get("site_id") for _, r in config_rows):
        try:
            site_uuid = resolve_site_uuid(site_id)
            if site_uuid is None:
                logger.error("No site found and cannot create")
                return {
                    "rows_inserted": 0,
                    "points_created": 0,
                    "errors": ["No site available"],
                }
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
            except ValueError:
                errors.append(f"Invalid device_id: {device_id_str}")
                continue
            except IndexError:
                errors.append(f"Invalid device_id: {device_id_str}")
                continue

            logger.info(
                "BACnet device %s: reading %d points (RPC)", device_id_str, len(points)
            )
            # (oid_str, line_num, obj_name, row_site_id, row_external_id) when from data model
            point_specs: list[tuple[str, int, str, Optional[str], Optional[str]]] = []
            for line_num, r in points:
                oid_str = r.get("object_identifier", "").strip().strip('"')
                obj_name = (r.get("object_name") or "").strip() or oid_str.replace(
                    ",", "_"
                )
                row_site_id = (r.get("site_id") or "").strip() or None
                row_ext_id = (r.get("external_id") or "").strip() or None
                point_specs.append(
                    (oid_str, line_num, obj_name, row_site_id, row_ext_id)
                )

            # (row_site_id, row_ext_id, obj_name, val, oid_str) for points upsert
            device_readings: list[
                tuple[Optional[str], Optional[str], str, float, str]
            ] = []

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
                        oid_to_spec = {
                            s[0]: (
                                s[1],
                                s[2],
                                s[3] if len(s) > 3 else None,
                                s[4] if len(s) > 4 else None,
                            )
                            for s in point_specs
                        }
                        for idx, item in enumerate(rpm_results):
                            oid_str = str(item.get("object_identifier", "")).strip()
                            oid_from_spec = (
                                point_specs[idx][0]
                                if idx < len(point_specs)
                                else oid_str
                            )
                            t = oid_to_spec.get(
                                oid_str,
                                (
                                    (
                                        point_specs[idx][1],
                                        point_specs[idx][2],
                                        (
                                            point_specs[idx][3]
                                            if len(point_specs[idx]) > 3
                                            else None
                                        ),
                                        (
                                            point_specs[idx][4]
                                            if len(point_specs[idx]) > 4
                                            else None
                                        ),
                                    )
                                    if idx < len(point_specs)
                                    else (0, oid_str, None, None)
                                ),
                            )
                            line_num, obj_name = t[0], t[1]
                            row_sid, row_ext = t[2], t[3]
                            val_raw = item.get("value")
                            if isinstance(val_raw, str) and val_raw.startswith(
                                "Error:"
                            ):
                                errors.append(f"Line {line_num} {oid_str}: {val_raw}")
                            else:
                                val = _pv_to_float(val_raw)
                                if val is not None:
                                    device_readings.append(
                                        (row_sid, row_ext, obj_name, val, oid_from_spec)
                                    )
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
                for oid_str, line_num, obj_name, row_sid, row_ext in point_specs:
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
                                device_readings.append(
                                    (row_sid, row_ext, obj_name, val, oid_str)
                                )
                    except Exception as e:
                        errors.append(f"Line {line_num} {oid_str}: {e}")

            bacnet_device_id = str(device_instance)
            for row_sid, row_ext, obj_name, val, oid_str in device_readings:
                site_uuid_use = resolve_cached(row_sid) if row_sid else site_uuid
                if not site_uuid_use:
                    errors.append(f"No site for point {obj_name} (site_id={row_sid})")
                    continue
                ext_id_use = row_ext or obj_name
                readings.append(
                    (ts, str(site_uuid_use), ext_id_use, val, bacnet_device_id, oid_str)
                )

    rows_inserted = 0
    points_created = 0
    if readings:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for (
                    ts_r,
                    sid,
                    ext_id,
                    val,
                    bacnet_device_id,
                    object_identifier,
                ) in readings:
                    cur.execute(
                        """
                        INSERT INTO points (site_id, external_id, bacnet_device_id, object_identifier, object_name)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (site_id, external_id) DO UPDATE SET
                          bacnet_device_id = EXCLUDED.bacnet_device_id,
                          object_identifier = EXCLUDED.object_identifier,
                          object_name = EXCLUDED.object_name
                        RETURNING id
                        """,
                        (
                            sid,
                            ext_id,
                            bacnet_device_id,
                            object_identifier,
                            ext_id,
                        ),
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
    server_url: Optional[str] = None,
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

    # RPC-only: require URL (from arg or settings)
    server_url = server_url or settings.bacnet_server_url
    if not server_url:
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

    logger.info("BACnet scrape via RPC: %s (site=%s)", server_url, site_id)
    return await _scrape_via_rpc(
        csv_path, site_id, config_rows, by_device, server_url=server_url
    )


async def scrape_bacnet_from_data_model(
    site_id: Optional[str] = None,
    server_url: Optional[str] = None,
) -> dict:
    """
    Scrape BACnet present-values from points loaded from the data model (no CSV).
    Only points with bacnet_device_id and object_identifier set are read.
    Returns {rows_inserted, points_created, errors}.
    """
    settings = get_platform_settings()
    if not settings.bacnet_scrape_enabled:
        logger.info("BACnet scrape disabled (OFDD_BACNET_SCRAPE_ENABLED=false)")
        return {"rows_inserted": 0, "points_created": 0, "errors": ["Scrape disabled"]}

    points_list = get_bacnet_points_from_data_model(site_id=site_id)
    if not points_list:
        logger.info("No BACnet points in data model (site_id=%s)", site_id)
        return {"rows_inserted": 0, "points_created": 0, "errors": []}

    url = server_url or settings.bacnet_server_url
    if not url:
        logger.error("OFDD_BACNET_SERVER_URL required for data-model scrape")
        return {
            "rows_inserted": 0,
            "points_created": 0,
            "errors": ["Set OFDD_BACNET_SERVER_URL for RPC scrape"],
        }

    config_rows: list[tuple[int, dict]] = [
        (i + 1, r) for i, r in enumerate(points_list)
    ]
    by_device: dict[str, list[tuple[int, dict]]] = {}
    for line_num, r in config_rows:
        did = r.get("device_id", "").strip()
        if not did:
            continue
        if did not in by_device:
            by_device[did] = []
        by_device[did].append((line_num, r))

    logger.info(
        "BACnet scrape from data model: %s (%d points, %d devices)",
        url,
        len(points_list),
        len(by_device),
    )
    return await _scrape_via_rpc(
        None, site_id or "default", config_rows, by_device, server_url=url
    )


def run_bacnet_scrape(
    csv_path: Path,
    site_id: str = "default",
    equipment_id: str = "bacnet",
    server_url: Optional[str] = None,
) -> dict:
    """Synchronous wrapper for scrape_bacnet_from_csv. server_url overrides OFDD_BACNET_SERVER_URL when set."""
    return asyncio.run(
        scrape_bacnet_from_csv(csv_path, site_id, equipment_id, server_url=server_url)
    )


def run_bacnet_scrape_data_model(
    site_id: Optional[str] = None,
    server_url: Optional[str] = None,
) -> dict:
    """Synchronous wrapper for scrape_bacnet_from_data_model. Prefer over CSV when points have BACnet addressing."""
    return asyncio.run(
        scrape_bacnet_from_data_model(site_id=site_id, server_url=server_url)
    )
