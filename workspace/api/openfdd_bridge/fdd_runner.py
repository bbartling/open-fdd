"""Scheduled FDD batch runner.

Resolves which saved Rule Lab rules apply to which BRICK-modeled sites, runs
each rule across the best available timeseries (feather store, falling back to
the demo sample), and persists a summary that drives the building check-engine
light. Invoked on a timer by the ``openfdd-fdd-loop`` systemd unit::

    python -m openfdd_bridge.fdd_runner --once
    python -m openfdd_bridge.fdd_runner --loop --interval-hours 3
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from . import playground
from .data_loader import load_frame_for_run
from .fdd_row_prep import prepare_fdd_rows
from .fault_catalog import family_for_code
from .feather_store import FeatherStore
from .fdd_results import save_results
from .model_service import ModelService
from .rule_store import RuleStore

_log = logging.getLogger(__name__)

DEFAULT_LIMIT = 1000
DEFAULT_LOOKBACK_HOURS = float(__import__("os").environ.get("OFDD_FDD_LOOKBACK_HOURS", "1") or 1)
DEFAULT_INTERVAL_MINUTES = float(__import__("os").environ.get("OFDD_FDD_INTERVAL_MINUTES", "10") or 10)


def resolve_site_ids(model: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    """Resolve the data site ids a rule should run against from the BRICK model."""
    applies_to = rule.get("applies_to") if isinstance(rule.get("applies_to"), dict) else {}
    bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
    explicit = [str(s) for s in applies_to.get("site_ids", []) if str(s).strip()]
    if explicit:
        return explicit

    sites = [s for s in model.get("sites", []) if isinstance(s, dict)]
    equipment = [e for e in model.get("equipment", []) if isinstance(e, dict)]
    points = [p for p in model.get("points", []) if isinstance(p, dict)]

    matched_site_ids: set[str] = set()
    bound_points = {str(x) for x in bindings.get("point_ids") or [] if str(x).strip()}
    bound_eq = {str(x) for x in bindings.get("equipment_ids") or [] if str(x).strip()}
    bound_brick = {str(x) for x in bindings.get("brick_types") or [] if str(x).strip()}

    if bound_points or bound_eq or bound_brick:
        for pt in points:
            pid = str(pt.get("id") or "")
            eq_id = str(pt.get("equipment_id") or "")
            brick = str(pt.get("brick_type") or "")
            if bound_points and pid in bound_points and pt.get("site_id"):
                matched_site_ids.add(str(pt.get("site_id")))
            elif bound_eq and eq_id in bound_eq and pt.get("site_id"):
                matched_site_ids.add(str(pt.get("site_id")))
            elif bound_brick and brick in bound_brick and pt.get("site_id"):
                matched_site_ids.add(str(pt.get("site_id")))
        if matched_site_ids:
            return sorted(matched_site_ids)

    eq_type = str(applies_to.get("equipment_type") or "").strip()
    brick_type = str(applies_to.get("brick_type") or "").strip()
    if eq_type:
        for eq in equipment:
            if str(eq.get("equipment_type") or "") == eq_type and eq.get("site_id"):
                matched_site_ids.add(str(eq.get("site_id")))
    if brick_type:
        for pt in points:
            if str(pt.get("brick_type") or "") == brick_type and pt.get("site_id"):
                matched_site_ids.add(str(pt.get("site_id")))

    if eq_type or brick_type:
        ids = sorted(matched_site_ids)
    else:
        ids = sorted({str(s.get("id")) for s in sites if s.get("id")})

    if not ids:
        ids = sorted({entry["site_id"] for entry in FeatherStore().list_sites()})
    return ids or ["demo"]


def _rule_code(rule: dict[str, Any]) -> str:
    from .rule_source import read_source

    path = str(rule.get("source_path") or "")
    if path:
        disk = read_source(path)
        if disk.strip():
            return disk
    return str(rule.get("code") or "")


def _run_one(
    rule: dict[str, Any],
    site_id: str,
    *,
    limit: int,
    model: dict[str, Any],
    chunk_hours: float = 0,
    lookback_hours: float = 0,
) -> dict[str, Any]:
    import pandas as pd

    frame, origin = load_frame_for_run(site_id)
    if lookback_hours > 0 and "timestamp" in frame.columns:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=lookback_hours)
        ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        trimmed = frame.loc[ts >= cutoff].copy()
        if not trimmed.empty:
            frame = trimmed
    fault_code = str(rule.get("fault_code") or "")
    code = _rule_code(rule)
    base = {
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "site_id": site_id,
        "severity": rule.get("severity", "warning"),
        "source": origin,
        "fault_code": fault_code,
        "equipment_family": family_for_code(fault_code) or "",
    }
    try:
        if rule.get("mode") == "script":
            df = frame.head(limit) if limit and len(frame) > limit else frame
            result = playground.run_dataframe_script(code, df, cfg=rule.get("config") or {})
            if not result.get("ok"):
                return {**base, "status": "error", "rows": int(len(df)), "flagged": 0, "error": result.get("error", "")}
            flag_cols = result.get("flag_columns") or []
            flagged = 0
            for row in result.get("preview", []):
                if any(int(row.get(col) or 0) for col in flag_cols):
                    flagged += 1
            return {
                **base,
                "status": "ok",
                "rows": int(result.get("rows") or 0),
                "flagged": flagged,
                "flag_columns": flag_cols,
            }
        use_chunked = chunk_hours > 0 and len(frame) > 500
        if use_chunked:
            row_count, flagged, _events = playground.sweep_dataframe_chunked(
                code,
                rule.get("config") or {},
                frame,
                chunk_hours=chunk_hours,
                enrich_rows=lambda rows: rows,  # legacy path; prefer prepare_fdd_rows below
            )
            return {
                **base,
                "status": "ok",
                "rows": row_count,
                "flagged": int(flagged),
                "chunked": True,
                "chunk_hours": chunk_hours,
            }
        rows = prepare_fdd_rows(frame, rule, model, site_id, limit=limit or len(frame))
        flags, _events = playground.sweep_rule(code, rule.get("config") or {}, rows, capture_print=False)
        return {
            **base,
            "status": "ok",
            "rows": len(rows),
            "flagged": int(sum(1 for f in flags if f)),
        }
    except Exception as exc:  # noqa: BLE001 - surface as a run error, keep the batch going
        return {**base, "status": "error", "rows": 0, "flagged": 0, "error": str(exc)[:1000]}


def run_batch(
    *,
    limit: int = DEFAULT_LIMIT,
    persist: bool = True,
    chunk_hours: float = playground.GO_LIVE_BATCH_HOURS,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    use_chunks: bool | None = None,
) -> dict[str, Any]:
    started = time.time()
    model = ModelService().load()
    rules = [r for r in RuleStore().list_rules() if isinstance(r, dict) and r.get("enabled", True)]
    lookback = max(0.0, float(lookback_hours))
    chunk = chunk_hours if (use_chunks if use_chunks is not None else lookback > 6) else 0
    runs: list[dict[str, Any]] = []
    for rule in rules:
        for site_id in resolve_site_ids(model, rule):
            runs.append(
                _run_one(
                    rule,
                    site_id,
                    limit=limit,
                    model=model,
                    chunk_hours=chunk,
                    lookback_hours=lookback,
                )
            )
    summary = {
        "ok": True,
        "rules_run": len(rules),
        "site_runs": len(runs),
        "flagged_runs": sum(1 for r in runs if r.get("flagged")),
        "error_runs": sum(1 for r in runs if r.get("status") == "error"),
        "ms": int((time.time() - started) * 1000),
        "runs": runs,
        "chunk_hours": chunk if chunk else None,
        "lookback_hours": lookback,
    }
    if persist:
        doc = save_results(runs)
        summary["generated_at"] = doc["generated_at"]
    return summary


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Open-FDD scheduled batch runner")
    parser.add_argument("--once", action="store_true", help="run a single batch and exit (default)")
    parser.add_argument("--loop", action="store_true", help="run forever on interval")
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=float(os.environ.get("OFDD_RULE_INTERVAL_HOURS", "0") or 0),
        help="legacy hours interval (overridden by --interval-minutes when set)",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=DEFAULT_INTERVAL_MINUTES,
        help="minutes between batch runs when --loop (default from OFDD_FDD_INTERVAL_MINUTES)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=DEFAULT_LOOKBACK_HOURS,
        help="hours of feather history per AFDD pass (default 1)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def _cycle() -> None:
        result = run_batch(limit=args.limit, lookback_hours=args.lookback_hours)
        _log.info(
            "fdd batch: rules=%d site_runs=%d flagged=%d errors=%d lookback=%.1fh ms=%d",
            result["rules_run"],
            result["site_runs"],
            result["flagged_runs"],
            result["error_runs"],
            args.lookback_hours,
            result["ms"],
        )

    if args.loop:
        if args.interval_hours and args.interval_hours > 0 and args.interval_minutes == DEFAULT_INTERVAL_MINUTES:
            interval = max(60.0, args.interval_hours * 3600.0)
        else:
            interval = max(60.0, args.interval_minutes * 60.0)
        while True:
            _cycle()
            time.sleep(interval)
    _cycle()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
