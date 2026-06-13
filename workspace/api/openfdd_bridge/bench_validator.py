"""Cross-source bench validator: native BACnet direct vs Niagara baskStream."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .driver_point_contract import (
    canonical_source,
    normalize_bacnet_value,
    normalize_niagara_value,
    values_compatible,
)
from .paths import bacnet_poll_csv, data_dir, repo_root

_DEFAULT_CONFIG = data_dir() / "bench_bacnet_vs_niagara.yaml"


def load_bench_mapping(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or _DEFAULT_CONFIG
    if not cfg_path.is_file():
        raise FileNotFoundError(f"bench mapping not found: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _parse_ts(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_bacnet_samples() -> dict[str, dict[str, Any]]:
    """Last sample per point_id from BACnet poll CSV."""
    path = bacnet_poll_csv()
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = str(row.get("point_id") or "").strip()
            if not pid:
                continue
            ts = str(row.get("timestamp_utc") or "")
            prev = out.get(pid)
            if prev is None or ts >= str(prev.get("timestamp") or ""):
                out[pid] = {
                    "point_id": pid,
                    "value": row.get("value"),
                    "timestamp": ts,
                    "status": "ok",
                    "units": str(row.get("units") or ""),
                }
    return out


def _latest_niagara_values(station_id: str) -> dict[str, dict[str, Any]]:
    from .niagara_store import get_last_values, load_points_cache, make_point_id

    last = get_last_values(station_id)
    points = {p["point_ord"]: p for p in load_points_cache(station_id)}
    out: dict[str, dict[str, Any]] = {}
    for ord_value, row in last.items():
        meta = points.get(ord_value, {})
        pid = str(row.get("point_id") or make_point_id(station_id, ord_value))
        out[ord_value] = {**row, "point_id": pid, "point_ord": ord_value, **{k: meta.get(k) for k in ("units", "point_name")}}
    return out


def _bacnet_by_name(samples: dict[str, dict[str, Any]], names: list[str]) -> dict[str, Any] | None:
    from .paths import workspace_dir

    disc_path = workspace_dir() / "bacnet" / "commissioning" / "points_discovered.csv"
    if not disc_path.is_file():
        return None
    name_set = {n.lower() for n in names}
    with disc_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            obj_name = str(row.get("object_name") or "").strip().lower()
            pid = str(row.get("point_id") or "")
            if obj_name in name_set and pid in samples:
                return samples[pid]
    return None


def validate_bacnet_vs_niagara(
    *,
    config_path: Path | None = None,
    stale_after_polls: int = 3,
    poll_interval_s: int = 60,
) -> dict[str, Any]:
    """Compare latest BACnet direct vs Niagara values using bench mapping."""
    cfg = load_bench_mapping(config_path)
    device = cfg.get("bench_device") or {}
    tolerances = cfg.get("tolerances") or {}
    points_cfg = cfg.get("points") or {}
    station_id = str(device.get("niagara_station_id") or "bench9065")

    bacnet_samples = _latest_bacnet_samples()
    niagara_samples = _latest_niagara_values(station_id)

    stale_s = stale_after_polls * poll_interval_s
    now = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0

    for key, spec in points_cfg.items():
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind") or "numeric")
        tolerance = float(spec.get("tolerance") or tolerances.get("temperature_degF") or 1.0)
        if "humidity" in key:
            tolerance = float(spec.get("tolerance") or tolerances.get("humidity_percentRH") or 5.0)
        if "pressure" in key:
            tolerance = float(spec.get("tolerance") or tolerances.get("pressure_inH2O") or 0.10)

        bacnet_raw: dict[str, Any] | None = None
        bacnet_pid = spec.get("bacnet_point_id")
        if bacnet_pid and str(bacnet_pid) != "null":
            bacnet_raw = bacnet_samples.get(str(bacnet_pid))
        if bacnet_raw is None:
            bacnet_raw = _bacnet_by_name(bacnet_samples, list(spec.get("bacnet_names") or []))

        niagara_ord = str(spec.get("niagara_ord") or "")
        niagara_raw = niagara_samples.get(niagara_ord)

        semantic = str(spec.get("semantic_id") or key)
        b_norm = normalize_bacnet_value(
            point_id=str(bacnet_raw.get("point_id") if bacnet_raw else spec.get("bacnet_point_id") or ""),
            value=bacnet_raw.get("value") if bacnet_raw else None,
            timestamp=str(bacnet_raw.get("timestamp") if bacnet_raw else ""),
            status=str(bacnet_raw.get("status") if bacnet_raw else "missing"),
            units=str(bacnet_raw.get("units") if bacnet_raw else ""),
            semantic_point_id=semantic,
            source="bacnet_direct",
        )
        n_norm = normalize_niagara_value(
            niagara_raw or {"point_ord": niagara_ord, "value": None, "status": "missing"},
            semantic_point_id=semantic,
            source="niagara_baskstream",
        )

        cmp = values_compatible(
            b_norm,
            n_norm,
            kind=kind,
            tolerance=tolerance,
            timestamp_skew_s=float(tolerances.get("timestamp_skew_seconds") or 180),
        )

        stale_bacnet = False
        stale_niagara = False
        for label, norm in (("bacnet", b_norm), ("niagara", n_norm)):
            ts = _parse_ts(str(norm.get("timestamp") or ""))
            if ts and (now - ts).total_seconds() > stale_s:
                if label == "bacnet":
                    stale_bacnet = True
                else:
                    stale_niagara = True

        entry = {
            "semantic_point_id": semantic,
            "brick_type": spec.get("brick_type"),
            "pass": cmp["pass"] and not stale_bacnet and not stale_niagara and not cmp["missing_bacnet"] and not cmp["missing_niagara"],
            "kind": kind,
            "tolerance": tolerance,
            "abs_diff": cmp.get("abs_diff"),
            "timestamp_skew_s": cmp.get("timestamp_skew_s"),
            "reason": cmp.get("reason"),
            "stale_bacnet": stale_bacnet,
            "stale_niagara": stale_niagara,
            "missing_bacnet": cmp["missing_bacnet"],
            "missing_niagara": cmp["missing_niagara"],
            "bacnet": b_norm,
            "niagara": n_norm,
            "bacnet_point_id": spec.get("bacnet_point_id"),
            "niagara_ord": niagara_ord,
        }
        if entry["missing_bacnet"] and entry["missing_niagara"]:
            entry["pass"] = False
            entry["reason"] = "both sources missing"
            skipped += 1
        elif entry["pass"]:
            passed += 1
        else:
            failed += 1
        results.append(entry)

    total = len(results)
    score = round(100.0 * passed / total, 1) if total else 0.0
    overall = failed == 0 and skipped < total

    return {
        "ok": overall,
        "bench_device": device.get("name"),
        "bacnet_device_instance": device.get("bacnet_device_instance"),
        "niagara_station_id": station_id,
        "validated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "score_pct": score,
        },
        "tolerances": tolerances,
        "points": results,
        "sources": {
            "bacnet_direct": canonical_source("bacnet"),
            "niagara_baskstream": canonical_source("niagara_baskstream"),
        },
    }


def poll_cadence_report(
    *,
    source: str,
    station_id: str | None = None,
    expected_interval_s: int = 60,
    window_samples: int = 20,
) -> dict[str, Any]:
    """Estimate observed poll spacing from recent samples."""
    timestamps: list[datetime] = []
    if source in {"bacnet", "bacnet_direct"}:
        path = bacnet_poll_csv()
        if path.is_file():
            rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
            for row in rows[-window_samples * 10 :]:
                ts = _parse_ts(str(row.get("timestamp_utc") or ""))
                if ts:
                    timestamps.append(ts)
    elif source == "niagara_baskstream" and station_id:
        from .paths import niagara_poll_csv

        path = niagara_poll_csv()
        if path.is_file():
            rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
            for row in rows[-window_samples * 10 :]:
                if str(row.get("station_id") or "") != station_id:
                    continue
                ts = _parse_ts(str(row.get("timestamp_utc") or ""))
                if ts:
                    timestamps.append(ts)

    timestamps = sorted(set(timestamps))[-window_samples:]
    gaps: list[float] = []
    for i in range(1, len(timestamps)):
        gaps.append((timestamps[i] - timestamps[i - 1]).total_seconds())

    observed = sum(gaps) / len(gaps) if gaps else None
    low = expected_interval_s * 0.75
    high = expected_interval_s * 1.5
    if expected_interval_s <= 30:
        low, high = 20, 45
    elif expected_interval_s >= 120:
        low, high = 90, 150

    return {
        "source": canonical_source(source),
        "expected_interval_s": expected_interval_s,
        "observed_interval_s": round(observed, 1) if observed is not None else None,
        "sample_count": len(timestamps),
        "gap_count": len(gaps),
        "within_tolerance": observed is not None and low <= observed <= high,
        "tolerance_range_s": [low, high],
        "last_timestamp": timestamps[-1].isoformat() if timestamps else None,
    }


def export_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Bench validation: BACnet direct vs Niagara",
        "",
        f"- **Device:** {report.get('bench_device')}",
        f"- **Validated at:** {report.get('validated_at')}",
        f"- **Overall:** {'PASS' if report.get('ok') else 'FAIL'}",
        f"- **Score:** {report.get('summary', {}).get('score_pct')}%",
        "",
        "| Semantic | PASS | BACnet | Niagara | Diff | Reason |",
        "|----------|------|--------|---------|------|--------|",
    ]
    for pt in report.get("points") or []:
        b = pt.get("bacnet") or {}
        n = pt.get("niagara") or {}
        lines.append(
            f"| {pt.get('semantic_point_id')} | {'✓' if pt.get('pass') else '✗'} | "
            f"{b.get('value')} | {n.get('value')} | {pt.get('abs_diff') or '—'} | {pt.get('reason')} |"
        )
    return "\n".join(lines) + "\n"


def write_checkpoint_report(report: dict[str, Any], *, label: str = "checkpoint") -> dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo_root() / "reports" / "overnight_bench" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{label}.json"
    md_path = out_dir / f"{label}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(export_report_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "dir": str(out_dir)}
