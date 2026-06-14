"""High-level async Niagara connector operations."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from .niagara_baskstream_client import (
    AsyncNiagaraBaskStreamClient,
    NiagaraBaskStreamError,
    friendly_error,
)
from .niagara_discovery import (
    children_of,
    discover_from_tree_rows,
    discover_schedules_from_tree_rows,
    normalize_point_record,
    normalize_read_value,
    node_name,
    node_ord,
    should_follow_child,
)
from .niagara_store import (
    append_samples_and_ingest,
    get_station,
    load_points_cache,
    make_point_id,
    matches_patterns,
    record_last_values,
    resolve_password,
    save_points_cache,
    update_poll_state,
)

_log = logging.getLogger(__name__)
_CLIENTS: dict[str, AsyncNiagaraBaskStreamClient] = {}
_CLIENT_LOCK = asyncio.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _station_or_raise(station_id: str) -> dict[str, Any]:
    station = get_station(station_id)
    if station is None:
        raise KeyError(f"unknown station: {station_id}")
    return station


async def _login_client(station: dict[str, Any], *, persistent: bool) -> AsyncNiagaraBaskStreamClient:
    sid = str(station["id"])
    password = resolve_password(station)
    if not password:
        env_name = station.get("password_env") or "OPENFDD_NIAGARA_ADMIN_PASSWORD"
        raise NiagaraBaskStreamError(f"password env {env_name} is not set")

    async with _CLIENT_LOCK:
        if persistent and sid in _CLIENTS:
            client = _CLIENTS[sid]
        else:
            client = AsyncNiagaraBaskStreamClient(
                str(station["station_url"]),
                verify_tls=bool(station.get("verify_tls")),
            )
            if persistent:
                _CLIENTS[sid] = client

    try:
        await client.login(str(station["username"]), password)
        return client
    except NiagaraBaskStreamError as exc:
        raise NiagaraBaskStreamError(friendly_error(exc, station_url=str(station["station_url"]))) from exc


async def close_persistent_client(station_id: str) -> None:
    async with _CLIENT_LOCK:
        client = _CLIENTS.pop(station_id, None)
    if client is not None:
        await client.close()


async def test_station(station_id: str) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    client = await _login_client(station, persistent=False)
    try:
        health = await client.health()
        caps = await client.capabilities()
        ping = await client.ping()
        return {
            "ok": True,
            "health": health,
            "capabilities": caps,
            "ping": ping,
            "authenticated_user": health.get("authenticatedUser"),
        }
    finally:
        await client.close()


async def _async_walk_tree(
    client: AsyncNiagaraBaskStreamClient,
    base: str,
    *,
    depth: int,
    metadata: str,
    max_nodes: int,
    follow_external: bool,
) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    root_base = base.rstrip("/") or base

    async def walk(ord_value: str, remaining: int, indent: int) -> None:
        if len(rows) >= max_nodes:
            return
        try:
            response = await client.browse(ord_value, depth=1, metadata=metadata)
            node = response.get("node") or {}
        except Exception as exc:
            rows.append((indent, {"display": f"! browse failed: {ord_value}", "status": str(exc)}))
            return
        this_ord = node_ord(node) or ord_value
        if this_ord in seen:
            return
        seen.add(this_ord)
        rows.append((indent, node))
        if remaining <= 0:
            return
        for child in children_of(node):
            child_ord = node_ord(child)
            if not should_follow_child(root_base, child_ord, follow_external):
                continue
            await walk(child_ord, remaining - 1, indent + 1)

    await walk(base, depth, 0)
    return rows


async def browse_tree(
    station_id: str,
    *,
    base: str,
    depth: int = 3,
    metadata: str = "none",
    max_nodes: int = 1000,
    follow_external: bool | None = None,
) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    follow = bool(station.get("follow_external")) if follow_external is None else follow_external
    client = await _login_client(station, persistent=False)
    try:
        rows = await _async_walk_tree(
            client,
            base,
            depth=depth,
            metadata=metadata,
            max_nodes=max_nodes,
            follow_external=follow,
        )
        tree = [
            {
                "indent": indent,
                "name": node_name(node),
                "ord": node_ord(node),
                "type": node.get("typeSpec") or "",
                "status": node.get("status") or "",
            }
            for indent, node in rows
        ]
        return {"base": base, "depth": depth, "nodes": tree, "count": len(tree)}
    finally:
        await client.close()


async def discover_points(
    station_id: str,
    *,
    base: str | None = None,
    depth: int | None = None,
    query: str = "",
    follow_external: bool | None = None,
    include_proxy_ext: bool | None = None,
) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    root = base or station.get("default_points_root") or station.get("root_ord") or "slot:/Drivers"
    browse_depth = int(depth if depth is not None else station.get("browse_depth") or 4)
    max_nodes = int(station.get("max_nodes") or 2000)
    follow = bool(station.get("follow_external")) if follow_external is None else follow_external
    include_proxy = bool(station.get("include_proxy_ext")) if include_proxy_ext is None else include_proxy_ext

    client = await _login_client(station, persistent=False)
    try:
        rows = await _async_walk_tree(
            client,
            root,
            depth=browse_depth,
            metadata="full",
            max_nodes=max_nodes,
            follow_external=follow,
        )
        nodes = discover_from_tree_rows(rows, query=query, include_proxy_ext=include_proxy)
        device_ord = root
        device_name = root.rsplit("/", 1)[-1] if "/" in root else root
        discovered_at = _utc_now()
        points = []
        for node in nodes:
            node["discovered_at"] = discovered_at
            rec = normalize_point_record(
                node,
                station_id=str(station["id"]),
                station_name=str(station.get("name") or station["id"]),
                device_ord=device_ord,
                device_name=device_name,
            )
            if matches_patterns(rec, station):
                rec["point_id"] = make_point_id(str(station["id"]), rec["point_ord"])
                points.append(rec)
        save_points_cache(str(station["id"]), points)
        return {"station_id": station_id, "base": root, "count": len(points), "points": points}
    finally:
        await client.close()


async def read_point_ords(
    station_id: str,
    ords: list[str],
    *,
    chunk_size: int | None = None,
    store: bool = False,
) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    batch = int(chunk_size if chunk_size is not None else station.get("read_batch_size") or 50)
    if batch < 1:
        raise NiagaraBaskStreamError("read batch size must be >= 1")
    cached = {p["point_ord"]: p for p in load_points_cache(station_id)}
    client = await _login_client(station, persistent=False)
    values: list[dict[str, Any]] = []
    try:
        for i in range(0, len(ords), batch):
            chunk = ords[i : i + batch]
            response = await client.read(chunk)
            for raw in response.get("points") or []:
                meta = cached.get(str(raw.get("point") or ""), {})
                row = normalize_read_value(raw, station_id=station_id, meta=meta)
                row["point_id"] = make_point_id(station_id, row["point_ord"])
                values.append(row)
        record_last_values(station_id, values)
        ingest = {}
        if store and values:
            samples = [
                {
                    "timestamp_utc": _utc_now(),
                    "site_id": "",
                    "point_id": row["point_id"],
                    "station_id": station_id,
                    "point_ord": row["point_ord"],
                    "point_name": row["point_name"],
                    "value": row["value"],
                    "status": row.get("status"),
                    "source": "niagara_baskstream",
                }
                for row in values
            ]
            ingest = append_samples_and_ingest(samples)
        return {"station_id": station_id, "count": len(values), "values": values, "ingest": ingest}
    finally:
        await client.close()


async def list_schedules(
    station_id: str,
    *,
    base: str | None = None,
    depth: int = 5,
    query: str = "",
    read: bool = False,
) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    root = base or "slot:/Schedules"
    follow = bool(station.get("follow_external"))
    client = await _login_client(station, persistent=False)
    try:
        rows = await _async_walk_tree(
            client,
            root,
            depth=depth,
            metadata="full",
            max_nodes=int(station.get("max_nodes") or 2000),
            follow_external=follow,
        )
        schedules = discover_schedules_from_tree_rows(rows, query=query)
        out = []
        for node in schedules:
            item = {
                "name": node_name(node),
                "ord": node_ord(node),
                "type": node.get("typeSpec") or "",
                "status": node.get("status") or "",
            }
            if read and item["ord"]:
                try:
                    item["schedule"] = await client.read_schedule(item["ord"])
                except Exception as exc:
                    item["schedule_error"] = str(exc)[:200]
            out.append(item)
        return {"station_id": station_id, "base": root, "count": len(out), "schedules": out}
    finally:
        await client.close()


async def poll_station_once(station_id: str, *, persistent: bool = True) -> dict[str, Any]:
    station = _station_or_raise(station_id)
    points = load_points_cache(station_id)
    if not points:
        base = station.get("default_points_root") or station.get("root_ord")
        if base:
            await discover_points(station_id, base=str(base))
            points = load_points_cache(station_id)
    ords = [str(p["point_ord"]) for p in points if p.get("point_ord")]
    if not ords:
        update_poll_state(station_id, last_error="no discovered points", connected=False)
        return {"station_id": station_id, "samples": 0, "error": "no discovered points"}

    t0 = time.monotonic()
    client = await _login_client(station, persistent=persistent)
    batch = int(station.get("read_batch_size") or 50)
    values: list[dict[str, Any]] = []
    batches = 0
    try:
        cached = {p["point_ord"]: p for p in points}
        for i in range(0, len(ords), batch):
            chunk = ords[i : i + batch]
            response = await client.read(chunk)
            batches += 1
            for raw in response.get("points") or []:
                meta = cached.get(str(raw.get("point") or ""), {})
                row = normalize_read_value(raw, station_id=station_id, meta=meta)
                row["point_id"] = make_point_id(station_id, row["point_ord"])
                values.append(row)
        record_last_values(station_id, values)
        samples = [
            {
                "timestamp_utc": _utc_now(),
                "site_id": "",
                "point_id": row["point_id"],
                "station_id": station_id,
                "point_ord": row["point_ord"],
                "point_name": row["point_name"],
                "value": row["value"],
                "status": row.get("status"),
                "source": "niagara_baskstream",
            }
            for row in values
        ]
        ingest = append_samples_and_ingest(samples)
        duration_ms = int((time.monotonic() - t0) * 1000)
        update_poll_state(
            station_id,
            connected=True,
            last_success=_utc_now(),
            last_error="",
            active_points=len(values),
            last_poll_duration_ms=duration_ms,
            batch_count=batches,
        )
        return {
            "station_id": station_id,
            "samples": len(samples),
            "batches": batches,
            "duration_ms": duration_ms,
            "ingest": ingest,
        }
    except Exception as exc:
        update_poll_state(station_id, connected=False, last_error=str(exc)[:300])
        if persistent:
            await close_persistent_client(station_id)
        raise
    finally:
        if not persistent:
            await client.close()
