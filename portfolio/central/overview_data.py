"""Overview tab data — local collect CSV + optional live Edge."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio.central.fault_legends import short_fault_description
from portfolio.central.paths import data_dir
from portfolio.central.display_time import format_ts_local, tz_label


def _read_csv(name: str) -> pd.DataFrame:
    path = data_dir() / name
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.ParserError:
        return pd.read_csv(path, engine="python", on_bad_lines="warn")


def _site_checkin_rows(site_id: str) -> tuple[pd.Series | None, pd.Series | None]:
    df = _read_csv("checkins.csv")
    if df.empty:
        return None, None
    df = df.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    sub = df[df["site_id"] == site_id].sort_values("collected_at")
    if sub.empty:
        return None, None
    latest = sub.iloc[-1]
    prior = sub.iloc[-2] if len(sub) >= 2 else None
    return latest, prior


def csv_snapshot_meta(site_id: str) -> dict[str, Any]:
    """Human-readable offline snapshot detail for the Dashboard source line."""
    root = data_dir()
    files = ("checkins.csv", "faults_daily.csv", "run_hours_daily.csv", "overrides_daily.csv")
    lines: list[str] = []
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        df = _read_csv(name)
        n_site = int((df["site_id"] == site_id).sum()) if not df.empty and "site_id" in df.columns else 0
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        lines.append(
            f"{name}: {n_site} row(s) for {site_id}, updated {format_ts_local(mtime.isoformat())} {tz_label()}"
        )
    if not lines:
        return {
            "summary": "No portfolio/data/*.csv yet — click Refresh collect CSVs or run portfolio_collect.py",
            "files": [],
        }
    return {
        "summary": "Offline snapshot from portfolio_collect.py",
        "files": lines,
        "path": str(root),
    }


def overrides_p8_from_csv(site_id: str) -> list[dict[str, Any]]:
    df = _read_csv("overrides_daily.csv")
    if df.empty or "site_id" not in df.columns:
        return []
    sub = df[df["site_id"] == site_id].copy()
    if sub.empty:
        return []
    if "collected_at" in sub.columns:
        sub["collected_at"] = pd.to_datetime(sub["collected_at"], errors="coerce")
        last_ts = sub["collected_at"].max()
        sub = sub[sub["collected_at"] == last_ts]
    if "priority_level" in sub.columns:
        sub = sub[sub["priority_level"].astype(str).isin(("8", "8.0"))]
    points: list[dict[str, Any]] = []
    for _, row in sub.iterrows():
        dev = row.get("device_instance")
        name = str(row.get("object_name") or row.get("object_identifier") or "?")
        label = f"dev{int(dev)} · {name}" if pd.notna(dev) else name
        points.append(
            {
                "label": label,
                "device_instance": dev,
                "object_name": name,
                "value": row.get("value"),
            }
        )
    return points


def fault_pie_from_csv(site_id: str) -> list[dict[str, Any]]:
    df = _read_csv("faults_daily.csv")
    if df.empty:
        return []
    df = df.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    sub = df[df["site_id"] == site_id]
    if sub.empty:
        return []
    last_ts = sub["collected_at"].max()
    snap = sub[sub["collected_at"] == last_ts]
    out: list[dict[str, Any]] = []
    for _, row in snap.groupby("fault_code", as_index=False).agg({"active_count": "sum"}).iterrows():
        code = str(row.get("fault_code") or "unknown")
        count = int(row.get("active_count") or 0)
        if count > 0:
            out.append({"fault_code": code, "count": count, "description": short_fault_description(code=code)})
    return sorted(out, key=lambda x: -x["count"])


def build_overview_from_csv(site_id: str) -> dict[str, Any]:
    latest, prior = _site_checkin_rows(site_id)
    active = int(latest["alert_count"]) if latest is not None else 0
    prior_active = int(prior["alert_count"]) if prior is not None else active
    delta = active - prior_active
    if prior_active > 0:
        pct_change = round((delta / prior_active) * 100.0, 1)
    elif active > 0:
        pct_change = 100.0
    else:
        pct_change = 0.0

    meta = csv_snapshot_meta(site_id)
    op_overrides = int(latest.get("operator_overrides") or 0) if latest is not None else 0
    return {
        "site_id": site_id,
        "site_name": str(latest["site_name"]) if latest is not None else site_id,
        "active_faults": active,
        "prior_active_faults": prior_active,
        "fault_delta": delta,
        "fault_pct_change": pct_change,
        "last_collect_at": str(latest["collected_at"]) if latest is not None else None,
        "last_collect_at_local": format_ts_local(latest["collected_at"]) if latest is not None else None,
        "prior_collect_at": str(prior["collected_at"]) if prior is not None else None,
        "traffic": str(latest.get("traffic") or "") if latest is not None else "",
        "operator_overrides": op_overrides,
        "fault_pie": fault_pie_from_csv(site_id),
        "overrides_p8": overrides_p8_from_csv(site_id),
        "csv_snapshot": meta,
        "data_source": meta.get("summary") or "offline CSV",
        "tz_label": tz_label(),
    }


def build_overview(site_id: str, *, include_live: bool = True, fast: bool = True) -> dict[str, Any]:
    out = build_overview_from_csv(site_id)
    out["live_edge"] = None
    out["mechanical_narrative"] = None
    out["credentials_ok"] = False
    out["connection_ok"] = False
    out["last_connection_at"] = None
    out["last_connection_at_local"] = None
    out["overrides_source"] = "csv" if out.get("overrides_p8") else "none"
    out["fast_mode"] = fast
    out["model_tree_loaded"] = False

    if not include_live:
        return out

    try:
        from portfolio.central.edge_fetch import edge_client_for_site, run_parallel

        site_cfg, token, client = edge_client_for_site(site_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        def _summary() -> dict[str, Any]:
            from portfolio.central.building_summary import build_building_summary

            return build_building_summary(site_id, fast=fast)

        rollup_timeout = 8 if fast else 30
        results, parallel_errors = run_parallel(
            {
                "faults": lambda: client.get_faults_status(token=token),
                "summary": _summary,
                "rollup": lambda: client.get_portfolio_rollup(
                    site_id=site_id, token=token, timeout=rollup_timeout
                ),
            },
            max_workers=3,
        )

        summary = results.get("summary") or {}
        out["mechanical_narrative"] = summary.get("narrative")
        out["mechanical_counts"] = summary.get("counts")
        out["brick_site_id"] = summary.get("brick_site_id")
        out["brick_site_name"] = summary.get("brick_site_name")
        out["registry_name"] = summary.get("registry_name")
        out["feeds_chains"] = summary.get("feeds_chains") or []
        out["model_equipment"] = summary.get("model_equipment")
        out["model_points"] = summary.get("model_points")
        out["credentials_ok"] = True
        out["data_source_live"] = (
            "Edge REST (fast): parallel faults + health + ahus_vavs_zones"
            if fast
            else "Edge REST: full building summary"
        )
        out["connection_ok"] = True
        out["last_connection_at"] = now_iso
        out["last_connection_at_local"] = format_ts_local(now_iso)
        if parallel_errors:
            out["live_warnings"] = parallel_errors

        faults = results.get("faults") or {}
        rollup = results.get("rollup")
        if isinstance(rollup, dict):
            try:
                ov = rollup.get("overrides") if isinstance(rollup.get("overrides"), dict) else {}
                live_points: list[dict[str, Any]] = []
                for pt in ov.get("points") or []:
                    if not isinstance(pt, dict):
                        continue
                    dev = pt.get("device_instance")
                    name = str(pt.get("object_name") or pt.get("object_identifier") or "?")
                    label = f"dev{int(dev)} · {name}" if dev is not None else name
                    live_points.append(
                        {
                            "label": label,
                            "device_instance": dev,
                            "object_name": name,
                            "value": pt.get("value"),
                        }
                    )
                if live_points:
                    out["overrides_p8"] = live_points
                    out["overrides_source"] = "live"
                out["operator_overrides"] = int(
                    ov.get("operator_override_points") or out.get("operator_overrides") or 0
                )
            except Exception:
                pass
        elif parallel_errors.get("rollup"):
            out.setdefault("live_warnings", {})["rollup"] = parallel_errors["rollup"]

        live_count = int(faults.get("alert_count") or 0)
        out["live_edge"] = {
            "active_faults": live_count,
            "traffic": faults.get("traffic"),
        }
        families = faults.get("families") if isinstance(faults.get("families"), list) else []
        live_pie: list[dict[str, Any]] = []
        for fam in families:
            if not isinstance(fam, dict):
                continue
            for f in fam.get("faults") or []:
                if not isinstance(f, dict):
                    continue
                code = str(f.get("code") or f.get("fault_code") or f.get("title") or "unknown")
                live_pie.append(
                    {
                        "fault_code": code,
                        "count": 1,
                        "description": short_fault_description(
                            code=code,
                            title=str(f.get("title") or ""),
                            rule_name=str(f.get("rule_name") or ""),
                            detail=str(f.get("detail") or "")[:80],
                        ),
                    }
                )
        if live_pie:
            merged: dict[str, dict[str, Any]] = {}
            for item in live_pie:
                code = item["fault_code"]
                bucket = merged.setdefault(
                    code,
                    {"fault_code": code, "count": 0, "description": item.get("description") or ""},
                )
                bucket["count"] += item["count"]
                if not bucket["description"] and item.get("description"):
                    bucket["description"] = item["description"]
            out["fault_pie"] = sorted(merged.values(), key=lambda x: -int(x["count"]))
            out["active_faults"] = live_count
    except Exception as exc:
        out["live_error"] = str(exc)[:300]
        out["connection_ok"] = False

    return out
