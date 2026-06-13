"""Niagara baskStream discovery helpers — preserves ORDs, filters proxy extensions."""

from __future__ import annotations

from typing import Any, Callable


def node_ord(node: dict[str, Any]) -> str:
    return str(node.get("slotPath") or node.get("ord") or "")


def node_name(node: dict[str, Any]) -> str:
    return str(node.get("display") or node.get("name") or node_ord(node))


def node_type(node: dict[str, Any]) -> str:
    return str(node.get("typeSpec") or node.get("description") or "")


def node_status(node: dict[str, Any]) -> str:
    return str(node.get("status") or "")


def classification(node: dict[str, Any]) -> dict[str, Any]:
    return ((node.get("metadata") or {}).get("classification") or {})


def is_proxy_extension(node: dict[str, Any]) -> bool:
    ord_value = node_ord(node).lower()
    name = node_name(node).strip().lower()
    if ord_value.endswith("/proxyext"):
        return True
    if name in {"proxy ext", "proxyext"}:
        return True
    t = node_type(node).lower()
    return "proxyext" in t or "bacnetproxyext" in t


def is_point(node: dict[str, Any], *, include_proxy_ext: bool = False) -> bool:
    if not include_proxy_ext and is_proxy_extension(node):
        return False
    c = classification(node)
    if c.get("isPoint") or c.get("isControlPoint") or c.get("isProxyPoint") or c.get("isStatusValue"):
        return True
    t = node_type(node).lower()
    if t.startswith("control:") and (
        "point" in t or "writable" in t or "numeric" in t or "boolean" in t
    ):
        return True
    if t.startswith("kitcontrol:") and "read" in (node.get("operations") or []):
        return True
    return False


def is_schedule(node: dict[str, Any]) -> bool:
    c = classification(node)
    if c.get("isSchedule"):
        return True
    if "read_schedule" in (node.get("operations") or []):
        return True
    return "schedule" in node_type(node).lower()


def children_of(node: dict[str, Any]) -> list[dict[str, Any]]:
    return list(node.get("children") or [])


def should_follow_child(base: str, child_ord: str, follow_external: bool) -> bool:
    if not child_ord:
        return False
    if follow_external:
        return True
    if child_ord == "slot:/" and base != "slot:/":
        return False
    normalized_base = base.rstrip("/")
    if normalized_base and not child_ord.startswith(normalized_base):
        if normalized_base == "slot:":
            return True
        return False
    return True


def normalize_point_record(
    node: dict[str, Any],
    *,
    station_id: str,
    station_name: str,
    device_ord: str = "",
    device_name: str = "",
    source: str = "niagara_baskstream",
) -> dict[str, Any]:
    ord_value = node_ord(node)
    return {
        "station_id": station_id,
        "station_name": station_name,
        "device_ord": device_ord,
        "device_name": device_name,
        "point_ord": ord_value,
        "point_name": node_name(node),
        "display_name": node_name(node),
        "type_spec": node_type(node),
        "value_type": str(node.get("valueType") or ""),
        "kind": str(classification(node).get("kind") or ""),
        "writable": bool(node.get("writable")),
        "status": node_status(node),
        "ok": node.get("ok"),
        "facets": node.get("facets"),
        "units": str(node.get("units") or ""),
        "source": source,
        "driver_path": ord_value,
        "discovered_at": node.get("discovered_at") or "",
    }


def normalize_read_value(
    row: dict[str, Any],
    *,
    station_id: str,
    meta: dict[str, Any] | None = None,
    source: str = "niagara_baskstream",
) -> dict[str, Any]:
    meta = meta or {}
    value = row.get("displayValue")
    if value in (None, ""):
        value = row.get("value")
    point_ord = str(row.get("point") or row.get("ord") or node_ord(meta))
    return {
        "station_id": station_id,
        "point_ord": point_ord,
        "point_name": str(row.get("displayName") or node_name(meta)),
        "value": value,
        "display_value": row.get("displayValue") if row.get("displayValue") not in (None, "") else value,
        "status": row.get("status"),
        "ok": row.get("ok"),
        "value_type": str(row.get("valueType") or node_type(meta)),
        "timestamp": row.get("timestamp"),
        "source": source,
    }


def discover_from_tree_rows(
    rows: list[tuple[int, dict[str, Any]]],
    *,
    query: str = "",
    include_proxy_ext: bool = False,
) -> list[dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    query_l = query.lower().strip()
    for _indent, node in rows:
        if not is_point(node, include_proxy_ext=include_proxy_ext):
            continue
        ord_value = node_ord(node)
        if not ord_value:
            continue
        haystack = " ".join([node_name(node), ord_value, node_type(node)]).lower()
        if query_l and query_l not in haystack:
            continue
        matches[ord_value] = node
    return [matches[k] for k in sorted(matches)]


def discover_schedules_from_tree_rows(
    rows: list[tuple[int, dict[str, Any]]],
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    query_l = query.lower().strip()
    for _indent, node in rows:
        if not is_schedule(node):
            continue
        ord_value = node_ord(node)
        if not ord_value:
            continue
        haystack = " ".join([node_name(node), ord_value, node_type(node)]).lower()
        if query_l and query_l not in haystack:
            continue
        matches[ord_value] = node
    return [matches[k] for k in sorted(matches)]


BrowseFn = Callable[[str, int, str], dict[str, Any]]


def walk_tree(
    browse_fn: BrowseFn,
    base: str,
    *,
    depth: int,
    metadata: str = "none",
    max_nodes: int = 2000,
    follow_external: bool = False,
) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    root_base = base.rstrip("/") or base

    def walk(ord_value: str, remaining: int, indent: int) -> None:
        if len(rows) >= max_nodes:
            return
        try:
            response = browse_fn(ord_value, 1, metadata)
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
            walk(child_ord, remaining - 1, indent + 1)

    walk(base, depth, 0)
    return rows
