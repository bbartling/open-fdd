#!/usr/bin/env python3
"""Gate A3 — SPARQL point → Timescale history → pandas DataFrame.

  python scripts/stress/03_sparql_zone_dataframe.py --building-id SYNTH_01
  python scripts/stress/03_sparql_zone_dataframe.py --host <lab-ip> --building-id SYNTH_01

Primary Soft-OPEN path (Timescale tip):
  SPARQL → mint ``urn:openfdd:site/…/point/…`` → ``GET /api/model/point-resolve?include_history=true``

Fallbacks: ``POST /api/historian/query``, ``GET /api/timeseries/readings``.
Soft-OPEN ≠ FQ. Synthetic sites only.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import (  # noqa: E402
    banner,
    client,
    get_timeseries_readings,
    historian_query,
    login,
    mint_opaque_point_iri,
    parse_connection,
    point_resolve,
    post_sparql,
    print_table,
    require_building_id,
    record_check,
    run_child,
    safe_print,
    wait_until_ready,
)

ZONE_OR_TEMP_RQ = """\
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX phScience: <https://project-haystack.org/def/phScience/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT DISTINCT ?point ?equipmentId ?pointId ?column ?fddSelection WHERE {
  ?point a phIoT:point ; phIoT:equipRef ?equip ;
    ph:hasTag phScience:temp, phIoT:sensor .
  ?equip ofdd:equipmentId ?equipmentId .
  OPTIONAL { ?point ofdd:pointId ?pointId . }
  OPTIONAL { ?point ofdd:column ?column . }
  OPTIONAL { ?point ofdd:fddSelection ?fddSelection . }
}
ORDER BY ?equipmentId ?point
LIMIT 50
"""


def _pick_point(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        raise SystemExit("no temp/zone/sat points in package RDF for building_id")
    # This is a single transport smoke, not an automatic FDD input approval.
    # Query order is deterministic within the semantically selected cohort.
    return rows[0]


def _df_from_samples(samples: list, *, column: str):
    import pandas as pd

    if not samples:
        return None
    ts_vals: list[tuple[str, float]] = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        ts = s.get("ts") or s.get("timestamp") or s.get("time")
        raw = s.get("val") if "val" in s else s.get("value")
        if ts is None or raw is None:
            continue
        try:
            ts_vals.append((str(ts), float(raw)))
        except (TypeError, ValueError):
            continue
    if not ts_vals:
        return None
    idx = pd.to_datetime([t for t, _ in ts_vals], utc=True, errors="coerce")
    df = pd.DataFrame({column: [v for _, v in ts_vals]}, index=idx)
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _df_from_historian(body: dict, *, equipment_id: str, column: str):
    import pandas as pd

    rows = body.get("rows") or []
    if body.get("truncated"):
        safe_print(
            f"FAIL: historian query truncated (returned={body.get('returned')} "
            f"row_count={body.get('row_count')}) — fail-closed"
        )
        return None, True
    ts_vals: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or row.get("device_id") or "")
        if equipment_id and eid and eid != equipment_id:
            continue
        ts = row.get("timestamp") or row.get("ts") or row.get("time")
        if ts is None:
            continue
        raw = row.get(column)
        if raw is None and isinstance(row.get("values"), dict):
            raw = row["values"].get(column)
        if raw is None:
            continue
        try:
            ts_vals.append((str(ts), float(raw)))
        except (TypeError, ValueError):
            continue
    if not ts_vals:
        return None, False
    idx = pd.to_datetime([t for t, _ in ts_vals], utc=True, errors="coerce")
    df = pd.DataFrame({column: [v for _, v in ts_vals]}, index=idx)
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df, False


def _df_from_readings(body: dict, *, column_key: str):
    import pandas as pd

    timestamps = body.get("timestamps") or []
    series = (body.get("series") or {}).get(column_key) or []
    if body.get("chart_truncated") or body.get("truncated"):
        safe_print("FAIL: timeseries readings truncated — fail-closed")
        return None, True
    if not timestamps or not series:
        return None, False
    n = min(len(timestamps), len(series))
    vals: list[float] = []
    keep_ts: list[str] = []
    for i in range(n):
        raw = series[i]
        if raw is None:
            continue
        try:
            vals.append(float(raw))
            keep_ts.append(str(timestamps[i]))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None, False
    idx = pd.to_datetime(keep_ts, utc=True, errors="coerce")
    df = pd.DataFrame({column_key: vals}, index=idx)
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df, False


def fetch_point_dataframe(
    http,
    headers: dict[str, str],
    *,
    building_id: str,
    equipment_id: str,
    column: str,
    point_iri: str | None = None,
):
    """Prefer Soft-OPEN point-resolve history; then historian; then readings."""
    iri = point_iri or mint_opaque_point_iri(building_id, equipment_id, column)
    safe_print(f"  point-resolve iri={iri}")
    try:
        body = point_resolve(http, headers, point_iri=iri, include_history=True, max_points=2000)
        hist = body.get("history") if isinstance(body.get("history"), dict) else {}
        if body.get("ok") is False or hist.get("ok") is False:
            raise RuntimeError("point-resolve/history reported failure")
        samples = hist.get("samples") or []
        max_pts = hist.get("max_points") or body.get("max_points") or 2000
        point_count = hist.get("point_count")
        if (
            body.get("truncated") is True or hist.get("truncated") is True
            or (isinstance(max_pts, int)
                and (len(samples) >= max_pts or (isinstance(point_count, int) and point_count >= max_pts)))
        ):
            safe_print(
                f"FAIL: point-resolve history hit max_points={max_pts} "
                f"(point_count={point_count}) — fail-closed on truncation"
            )
            return None, body, True
        safe_print(
            f"  point-resolve ok={body.get('ok')} openfdd_key={body.get('openfdd_key')} "
            f"samples={len(samples)} source={hist.get('source')}"
        )
        df = _df_from_samples(samples, column=column)
        if df is not None:
            df.attrs.update(
                equipment_id=equipment_id,
                building_id=building_id,
                openfdd_key=body.get("openfdd_key"),
                point_iri=iri,
            )
            return df, body, False
        if hist.get("ok") is False:
            safe_print(f"  history error: {hist.get('error')}")
    except RuntimeError as exc:
        safe_print(f"  point-resolve unavailable ({exc})")

    if point_iri:
        # Reconstructing a key or selecting a different series would conceal a
        # broken graph-to-history binding in this explicit semantic path.
        return None, {}, False

    safe_print(f"  historian query equipment_id={equipment_id!r} column={column!r}")
    try:
        body = historian_query(
            http, headers, site_id=building_id, equipment_id=equipment_id, limit=10_000
        )
        safe_print(
            f"  historian ok={body.get('ok')} configured={body.get('configured')} "
            f"row_count={body.get('row_count')} truncated={body.get('truncated')}"
        )
        df, trunc_fail = _df_from_historian(body, equipment_id=equipment_id, column=column)
        if trunc_fail:
            return None, body, True
        if df is not None:
            return df, body, False
    except RuntimeError as exc:
        safe_print(f"  historian query unavailable ({exc})")

    col_param = f"{equipment_id}:{column}" if equipment_id else column
    safe_print(f"  timeseries readings columns={col_param!r}")
    try:
        body = get_timeseries_readings(
            http, headers, site_id=building_id, columns=col_param, all_rows=True
        )
        series_keys = list((body.get("series") or {}).keys())
        key = col_param if col_param in series_keys else (column if column in series_keys else None)
        if key is None and series_keys:
            key = series_keys[0]
        if key is None:
            return None, body, False
        df, trunc_fail = _df_from_readings(body, column_key=key)
        if trunc_fail:
            return None, body, True
        return df, body, False
    except RuntimeError as exc:
        safe_print(f"  readings unavailable ({exc})")
        return None, {}, False


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    base = args.base_url
    building_id = require_building_id(args)
    banner(
        "Stress 03 — DataFrame via SPARQL + point-resolve/historian",
        base_url=base,
        building_id=building_id,
    )

    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)

        try:
            rows = post_sparql(http, headers, building_id=building_id, query=ZONE_OR_TEMP_RQ)
        except RuntimeError as exc:
            safe_print(f"FAIL: SPARQL point discovery — {exc}")
            return 1
        print_table("Temp/zone/sat candidate points", rows)
        if not rows:
            safe_print("BLOCKED: no semantically selected measured temperature points")
            return 2
        meta = _pick_point(rows)
        equipment_id = (meta.get("equipmentId") or meta.get("equipment_id") or "").strip()
        column = (meta.get("column") or meta.get("pointId") or "").strip()
        point_iri = meta.get("point")
        if not equipment_id or not column or not point_iri:
            safe_print(f"FAIL: could not resolve equipmentId/column from {meta!r}")
            return 1
        safe_print(f"  selected equipment_id={equipment_id} column={column}")

        df, _body, trunc_fail = fetch_point_dataframe(
            http,
            headers,
            building_id=building_id,
            equipment_id=equipment_id,
            column=column,
            point_iri=point_iri,
        )

    if trunc_fail:
        return 1
    if df is None or df.empty:
        safe_print(
            "\nBLOCKED 03 — graph discovered but no samples; data-path proof did not run"
        )
        return 2

    record_check("historian_samples", True)
    import numpy as np
    record_check("dataframe", bool(np.isfinite(df.to_numpy(dtype=float)).any()), comparisons=len(df))

    safe_print(f"\nDataFrame shape={df.shape}  columns={list(df.columns)}")
    safe_print(df.head(3))
    safe_print("\nPASS 03 — SPARQL → point-resolve/historian → DataFrame")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_child(main, "03_sparql_zone_dataframe.py"))
