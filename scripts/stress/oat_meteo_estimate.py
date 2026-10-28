#!/usr/bin/env python3
"""Read-only OAT-METEO fault-hour estimator (pandas oracle path).

Uses the same merge_asof web alignment, cadence bound, and confirm window as the
OAT-METEO rule cookbook. Intended for live W10 checks: SQL OAT-METEO fault hours
should be within 10% of this estimate on windows with material BAS vs web offset.

Does not write to the stack (readings query + local recompute only).

  python scripts/stress/oat_meteo_estimate.py --building-id SYNTH_01
  python scripts/stress/oat_meteo_estimate.py --host 127.0.0.1 --building-id SITE \\
      --start 2026-06-01T00:00:00Z --end 2026-06-02T00:00:00Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import (  # noqa: E402
    EXIT_FAIL,
    EXIT_PASS,
    add_connection_args,
    analytics_post,
    apply_base_url,
    banner,
    client,
    get_timeseries_readings,
    login,
    require_building_id,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

from open_fdd.rules.base import confirm_fault, hours_true  # noqa: E402
from open_fdd.rules.cookbook_catalog import oat_vs_meteo  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_args(parser)
    parser.add_argument("--equipment-id", default="", help="Optional equipment id filter")
    parser.add_argument("--start", default="", help="ISO window start (optional)")
    parser.add_argument("--end", default="", help="ISO window end (optional)")
    parser.add_argument(
        "--oa-column",
        default="",
        help="Open-FDD openfdd_key for local OAT (default: resolved primary/default site oa_t)",
    )
    parser.add_argument(
        "--web-column",
        default="web_oa_t",
        help="Readings column key for web OAT (default web_oa_t)",
    )
    return parser


def _series_from_readings(body: dict, column_key: str) -> list[tuple[str, float]]:
    timestamps = body.get("timestamps") or []
    series = (body.get("series") or {}).get(column_key) or []
    if body.get("chart_truncated") or body.get("truncated"):
        raise ValueError("timeseries readings truncated — fail-closed")
    out: list[tuple[str, float]] = []
    n = min(len(timestamps), len(series))
    for i in range(n):
        raw = series[i]
        if raw is None:
            continue
        out.append((str(timestamps[i]), float(raw)))
    return out


def _frame_from_readings(
    oa_body: dict,
    web_body: dict,
    *,
    oa_column: str,
    web_column: str,
) -> tuple[object, dict]:
    import pandas as pd

    oa_pairs = _series_from_readings(oa_body, oa_column)
    web_pairs = _series_from_readings(web_body, web_column)
    if not oa_pairs:
        raise ValueError(f"no local OAT readings for column {oa_column}")
    if not web_pairs:
        raise ValueError(f"no web OAT readings for column {web_column}")
    oa_idx = pd.to_datetime([t for t, _ in oa_pairs], utc=True, errors="coerce")
    web_idx = pd.to_datetime([t for t, _ in web_pairs], utc=True, errors="coerce")
    oa = pd.Series([v for _, v in oa_pairs], index=oa_idx, name="outside-air-temp")
    web = pd.Series([v for _, v in web_pairs], index=web_idx, name="web-outside-air-temp")
    oa = oa[~oa.index.isna()].sort_index()
    web = web[~web.index.isna()].sort_index()
    out = pd.concat([oa, web], axis=1).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    params = {
        "oat_err": 5.0,
        "web_cadence_seconds": 1200.0,
        "web_asof_margin_seconds": 300.0,
    }
    web_native = out[["web-outside-air-temp"]].dropna()
    out.attrs["web_oat_native_frame"] = web_native
    return out, params


def estimate_fault_hours(
    rows: list[dict],
    *,
    oa_col: str = "oa_t",
    poll_seconds: float = 300.0,
    confirm_seconds: float = 900.0,
) -> dict:
    frame, params = _frame_from_historian(rows, oa_col=oa_col)
    raw = oat_vs_meteo(frame, params, poll_seconds)
    confirmed = confirm_fault(raw, poll_seconds=poll_seconds, confirm_seconds=confirm_seconds)
    fault_hours = hours_true(confirmed, poll_seconds)
    return {
        "fault_hours": fault_hours,
        "poll_seconds": poll_seconds,
        "confirm_seconds": confirm_seconds,
        "web_asof_bound_seconds": params["web_cadence_seconds"] + params["web_asof_margin_seconds"],
        "oa_column": oa_col,
        "row_count": len(rows),
    }


def estimate_fault_hours_from_readings(
    oa_body: dict,
    web_body: dict,
    *,
    oa_column: str,
    web_column: str,
    poll_seconds: float = 300.0,
    confirm_seconds: float = 900.0,
) -> dict:
    frame, params = _frame_from_readings(
        oa_body,
        web_body,
        oa_column=oa_column,
        web_column=web_column,
    )
    raw = oat_vs_meteo(frame, params, poll_seconds)
    confirmed = confirm_fault(raw, poll_seconds=poll_seconds, confirm_seconds=confirm_seconds)
    fault_hours = hours_true(confirmed, poll_seconds)
    return {
        "fault_hours": fault_hours,
        "poll_seconds": poll_seconds,
        "confirm_seconds": confirm_seconds,
        "web_asof_bound_seconds": params["web_cadence_seconds"] + params["web_asof_margin_seconds"],
        "oa_column": oa_column,
        "web_column": web_column,
        "row_count": int(len(frame)),
    }


def _frame_from_historian(rows: list[dict], *, oa_col: str) -> tuple[object, dict]:
    import pandas as pd

    if not rows:
        raise ValueError("historian returned no rows")
    df = pd.DataFrame(rows)
    if "timestamp_utc" not in df.columns:
        raise ValueError("historian rows missing timestamp_utc")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.set_index("timestamp_utc").sort_index()
    params = {
        "oat_err": 5.0,
        "web_cadence_seconds": 1200.0,
        "web_asof_margin_seconds": 300.0,
    }
    if oa_col not in df.columns:
        raise ValueError(f"missing local OAT column {oa_col}")
    if "web_oa_t" not in df.columns and "web-outside-air-temp" not in df.columns:
        raise ValueError("missing web OAT column")
    out = df.rename(
        columns={
            oa_col: "outside-air-temp",
            "web_oa_t": "web-outside-air-temp",
        }
    )
    if "web-outside-air-temp" not in out.columns and "web_oa_t" in df.columns:
        out["web-outside-air-temp"] = df["web_oa_t"]
    web_native = out[["web-outside-air-temp"]].dropna()
    out.attrs["web_oat_native_frame"] = web_native
    return out, params


def resolve_oa_column(http, headers: dict[str, str], building_id: str, explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    meta = analytics_post(
        http,
        headers,
        "/api/analytics/bas-vs-web-oat",
        {"building_id": building_id, "max_points": 50},
    )
    analytics = meta.get("analytics") or meta
    ref = analytics.get("oa_t_reference") or {}
    key = ref.get("openfdd_key")
    if not key:
        raise ValueError("could not resolve site oa_t openfdd_key from bas-vs-web-oat metadata")
    return str(key)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    building_id = require_building_id(args)
    base = resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    apply_base_url(base)
    banner("oat_meteo_estimate", base_url=base, building_id=building_id)
    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        oa_column = resolve_oa_column(http, headers, building_id, args.oa_column)
        web_column = args.web_column.strip() or "web_oa_t"
        oa_body = get_timeseries_readings(
            http,
            headers,
            site_id=building_id,
            columns=oa_column,
            all_rows=True,
        )
        web_body = get_timeseries_readings(
            http,
            headers,
            site_id=building_id,
            columns=web_column,
            all_rows=True,
        )
        try:
            result = estimate_fault_hours_from_readings(
                oa_body,
                web_body,
                oa_column=oa_column,
                web_column=web_column,
            )
        except ValueError as exc:
            safe_print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return EXIT_FAIL
    payload = {"ok": True, "building_id": building_id, **result}
    safe_print(json.dumps(payload, indent=2))
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
