"""Feather-store timeseries reads for the Plot tab (web_lambda-style multi-series)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .data_loader import load_site_frame
from .feather_store import FeatherStore
from .model_service import ModelService
from .site_defaults import ensure_default_site
from .ttl_service import TtlService


def plot_column_name(point: dict[str, Any]) -> str:
    """Feather column name for a model point (matches bacnet_poll_ingest._column_for_point without CSV)."""
    ext = str(point.get("external_id") or "").strip()
    if ext:
        return ext
    fdd = str(point.get("fdd_input") or "").strip()
    if fdd:
        return fdd
    pid = str(point.get("id") or "").strip()
    # Full point id keeps VAV zone temps unique (many BACnet devices use analog-input,1).
    return pid


def historian_column_candidates(point: dict[str, Any]) -> list[str]:
    """Preference order when matching a model point to feather historian columns."""
    ext = str(point.get("external_id") or "").strip()
    if ext:
        return [ext]
    fdd = str(point.get("fdd_input") or "").strip()
    pid = str(point.get("id") or "").strip()
    out: list[str] = []
    if fdd:
        out.append(fdd)
    if pid:
        out.append(pid)
        if "-" in pid:
            short = pid.split("-", 1)[1]
            if short not in out:
                out.append(short)
    return out or [plot_column_name(point)]


def resolve_historian_column(point: dict[str, Any], available_columns: set[str] | list[str]) -> str:
    """Pick the feather column for ``point`` (full id preferred; short id for legacy shards)."""
    avail = set(available_columns)
    for col in historian_column_candidates(point):
        if col in avail:
            return col
    candidates = historian_column_candidates(point)
    return candidates[0] if candidates else plot_column_name(point)


def _equipment_for_site(model: dict[str, Any], site_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eq in model.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        if str(eq.get("site_id") or "") != site_id:
            continue
        eid = str(eq.get("id") or "").strip()
        if eid:
            out[eid] = eq
    return out


def _point_on_site(point: dict[str, Any], site_id: str, site_equipment: dict[str, dict[str, Any]]) -> bool:
    ps = str(point.get("site_id") or "").strip()
    if ps:
        return ps == site_id
    eid = str(point.get("equipment_id") or "").strip()
    return bool(eid and eid in site_equipment)


def columns_for_equipment(model: dict[str, Any], site_id: str, equipment_id: str) -> list[str]:
    """Feather column names for all points on one equipment row."""
    eid = str(equipment_id or "").strip()
    if not eid:
        return []
    site_eq = _equipment_for_site(model, site_id)
    cols: list[str] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or not _point_on_site(pt, site_id, site_eq):
            continue
        if str(pt.get("equipment_id") or "").strip() != eid:
            continue
        col = plot_column_name(pt)
        if col:
            cols.append(col)
    return sorted(set(cols))


def point_keys_for_equipment(model: dict[str, Any], site_id: str, equipment_id: str) -> list[str]:
    site_eq = _equipment_for_site(model, site_id)
    eid = str(equipment_id or "").strip()
    keys: list[str] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or not _point_on_site(pt, site_id, site_eq):
            continue
        if str(pt.get("equipment_id") or "").strip() != eid:
            continue
        pid = str(pt.get("id") or "").strip()
        if pid:
            keys.append(pid)
    return keys


def resolve_plot_columns(requested: list[str], model: dict[str, Any], site_id: str) -> list[str]:
    """Map point ids (or column names) to feather columns; dedupe in request order."""
    by_pid: dict[str, dict[str, Any]] = {}
    for pt in model.get("points") or []:
        if isinstance(pt, dict):
            pid = str(pt.get("id") or "").strip()
            if pid:
                by_pid[pid] = pt
    site_eq = _equipment_for_site(model, site_id)
    out: list[str] = []
    seen: set[str] = set()
    for name in requested:
        key = str(name or "").strip()
        if not key:
            continue
        pt = by_pid.get(key)
        if pt and _point_on_site(pt, site_id, site_eq):
            col = plot_column_name(pt)
        else:
            col = key
        if col and col not in seen:
            seen.add(col)
            out.append(col)
    return out


def build_plot_series_catalog(
    site_id: str,
    columns: list[str],
    model: dict[str, Any],
    labels: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (series_options, equipment_groups, unassigned_columns)."""
    col_set = set(columns)
    site_eq = _equipment_for_site(model, site_id)
    options: list[dict[str, Any]] = []
    mapped_cols: set[str] = set()

    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or not _point_on_site(pt, site_id, site_eq):
            continue
        col = plot_column_name(pt)
        if col not in col_set:
            continue
        eid = str(pt.get("equipment_id") or "").strip()
        key = str(pt.get("id") or col)
        label = str(pt.get("name") or pt.get("description") or labels.get(col) or col)
        options.append(
            {
                "key": key,
                "column": col,
                "equipment_id": eid,
                "label": label,
                "brick_type": str(pt.get("brick_type") or ""),
            }
        )
        mapped_cols.add(col)

    for col in columns:
        if col in mapped_cols:
            continue
        options.append(
            {
                "key": col,
                "column": col,
                "equipment_id": "",
                "label": labels.get(col, col),
            }
        )

    by_eq: dict[str, list[str]] = {}
    for opt in options:
        eid = str(opt.get("equipment_id") or "").strip() or "_unassigned"
        by_eq.setdefault(eid, []).append(str(opt["key"]))

    groups: list[dict[str, Any]] = []
    for eid, keys in by_eq.items():
        if eid == "_unassigned":
            continue
        meta = site_eq.get(eid, {})
        name = str(meta.get("name") or eid)
        inst = meta.get("bacnet_device_instance")
        if inst is None:
            inst = meta.get("bacnet_device_id")
        label = name
        eq_opts = [o for o in options if str(o.get("equipment_id") or "") == eid]
        eq_cols = sorted({str(o["column"]) for o in eq_opts})
        groups.append(
            {
                "equipment_id": eid,
                "name": name,
                "label": label,
                "bacnet_device_instance": inst,
                "keys": sorted(keys, key=lambda k: next((o["label"] for o in eq_opts if o["key"] == k), k)),
                "columns": eq_cols,
            }
        )

    def _sort_key(g: dict[str, Any]) -> tuple:
        inst = g.get("bacnet_device_instance")
        try:
            n = int(inst)
        except (TypeError, ValueError):
            n = 999_999
        return (n, str(g.get("name") or "").lower())

    groups.sort(key=_sort_key)

    unassigned_keys = by_eq.get("_unassigned", [])
    if unassigned_keys:
        groups.append(
            {
                "equipment_id": "",
                "name": "Unassigned",
                "label": "Unassigned columns",
                "bacnet_device_instance": None,
                "keys": sorted(unassigned_keys),
                "columns": sorted({o["column"] for o in options if o["key"] in unassigned_keys}),
            }
        )

    unassigned_columns = sorted(col_set - mapped_cols)
    return options, groups, unassigned_columns


def column_kinds_for_site(model: dict[str, Any], site_id: str) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") != site_id:
            continue
        ext = plot_column_name(pt)
        if not ext:
            continue
        brick = str(pt.get("brick_type") or "")
        if "Humidity" in brick:
            kinds[ext] = "humidity"
        else:
            kinds[ext] = "temperature"
    return kinds


def list_plot_sites() -> list[dict[str, str]]:
    from .model_sparql import list_model_sites

    model = ModelService()
    ensure_default_site(model, TtlService())
    sites = {s["site_id"]: s["name"] for s in list_model_sites(model.load())}
    demo_ids = {"demo", "site", "test", "sample", "default"}
    for entry in FeatherStore().list_sites():
        sid = str(entry.get("site_id") or "").strip()
        if sid and sid.lower() not in demo_ids and sid not in sites:
            sites[sid] = sid
    return [{"site_id": sid, "name": name} for sid, name in sorted(sites.items())]


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    skip = {"timestamp", "site_id", "building_id", "system_id"}
    cols: list[str] = []
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(str(col))
    return cols


def list_plot_series(site_id: str, *, source: str = "bacnet") -> dict[str, Any]:
    df = load_site_frame(site_id, source=source)
    model = ModelService().load()
    labels: dict[str, str] = {}
    for pt in model.get("points") or []:
        if not isinstance(pt, dict) or str(pt.get("site_id") or "") != site_id:
            continue
        ext = str(pt.get("external_id") or "").strip()
        if ext:
            labels[ext] = str(pt.get("description") or pt.get("brick_type") or ext)
    columns = _numeric_columns(df) if df is not None and not df.empty else []
    kinds = column_kinds_for_site(model, site_id)
    series_options, equipment_groups, unassigned_columns = build_plot_series_catalog(
        site_id, columns, model, labels
    )
    return {
        "site_id": site_id,
        "source": source,
        "columns": columns,
        "labels": labels,
        "kinds": kinds,
        "series_options": series_options,
        "equipment_groups": equipment_groups,
        "unassigned_columns": unassigned_columns,
        "row_count": int(len(df)) if df is not None else 0,
    }


def read_plot_series(
    site_id: str,
    columns: list[str],
    *,
    source: str = "bacnet",
    hours: int = 24,
    limit: int = 4000,
) -> dict[str, Any]:
    model = ModelService().load()
    columns = resolve_plot_columns(columns, model, site_id)
    df = load_site_frame(site_id, source=source)
    if df is None or df.empty:
        return {"site_id": site_id, "series": {}, "hours": hours}
    if "timestamp" in df.columns:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=max(1, hours))
        df = df[df["timestamp"] >= cutoff]
    df = df.sort_values("timestamp") if "timestamp" in df.columns else df
    if limit and len(df) > limit:
        df = df.tail(limit)
    ts_col = df["timestamp"].astype(str).tolist() if "timestamp" in df.columns else list(range(len(df)))
    series: dict[str, list[float | None]] = {}
    for col in columns:
        if col not in df.columns:
            continue
        vals: list[float | None] = []
        for v in df[col].tolist():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                vals.append(None)
            else:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    vals.append(None)
        series[col] = vals
    return {"site_id": site_id, "timestamps": ts_col, "series": series, "hours": hours}
