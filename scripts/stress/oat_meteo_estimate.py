#!/usr/bin/env python3
"""Read-only OAT-METEO fault-hour estimator (pandas oracle path).

Uses the same primary-reference selection, merge_asof web alignment, cadence bound,
and confirm window as the OAT-METEO rule cookbook. Intended for live W10 checks:
SQL OAT-METEO fault hours should be within 10% of this estimate on windows with
material BAS vs web offset.

Does not write to the stack (historian query + local recompute only).

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
    apply_base_url,
    banner,
    client,
    historian_query,
    login,
    require_building_id,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

from open_fdd.rules.base import confirm_fault, hours_true  # noqa: E402
from open_fdd.rules.cookbook_catalog import oat_vs_meteo  # noqa: E402


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_args(parser)
    parser.add_argument("--building-id", default="", help="Site/building id (required)")
    parser.add_argument("--equipment-id", default="", help="Optional AHU equipment id filter")
    parser.add_argument("--start", default="", help="ISO window start (optional)")
    parser.add_argument("--end", default="", help="ISO window end (optional)")
    parser.add_argument(
        "--oa-column",
        default="oa_t",
        help="Historian pivot column for local OAT (default oa_t)",
    )
    args = parser.parse_args()
    building_id = require_building_id(args.building_id)
    base = resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    apply_base_url(base)
    banner("oat_meteo_estimate", building_id=building_id, base=base)
    http = client()
    wait_until_ready(http)
    headers = login(http)
    body: dict = {"building_id": building_id, "roles": ["oa_t", "web_oa_t"]}
    if args.equipment_id.strip():
        body["equipment_id"] = args.equipment_id.strip()
    if args.start.strip():
        body["start"] = args.start.strip()
    if args.end.strip():
        body["end"] = args.end.strip()
    hist = historian_query(http, headers, body)
    rows = hist.get("rows") if isinstance(hist.get("rows"), list) else []
    try:
        result = estimate_fault_hours(rows, oa_col=args.oa_column.strip() or "oa_t")
    except ValueError as exc:
        safe_print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return EXIT_FAIL
    payload = {"ok": True, "building_id": building_id, **result}
    safe_print(json.dumps(payload, indent=2))
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
