#!/usr/bin/env python3
"""Read-only IP baseline capture for the 4.0.7 SI cutover (#1284).

For each configured site (JWT env file + sites JSON — no site names in code):
  * SQL IP FDD: fault/covered seconds and status per rule × equipment × UTC day
    (``POST /api/fdd/run`` bulk window, then ``fdd_interval_result`` hourly buckets
    rolled up to UTC calendar days)
  * Analytics: row payloads for every shipped ``POST /api/analytics/*`` route
  * Pandas IP on the same historian frames (``open_fdd`` + imperial ``unit_system``)
  * Unit inventory: role, ``point_map.unit``, ``sample.unit``, package ``unit_system``,
    and the W2c-style resolved source unit (overlay → tag → column → package default)
  * Sample row counts + sha256 manifest under ``~/openfdd-si-cutover/baseline-<sha>-<date>/``

Telemetry tables (``sample``, ``point_map``, ``authorized_series``) must not change.
``fdd_run`` / ``fdd_interval_result`` / ``analytics_result`` may grow from read-side
compute; persisted run ids are recorded for W2c invalidation.

CI:
  ``--self-test`` — offline shape check (no network)
  ``--emit-ip-goldens DIR`` — write compact JSON goldens for cookbook/SYNTH fixtures

Example:
  python3 scripts/stress/si_cutover/capture_ip_baseline.py \\
    --jwt-env ~/.config/openfdd/agent.env \\
    --sites-config ~/.config/openfdd/si-cutover-sites.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
STRESS = REPO / "scripts" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from helpers import (  # noqa: E402
    add_connection_args,
    analytics_post,
    apply_base_url,
    client,
    login,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

from si_cutover.baseline_io import (  # noqa: E402
    JsonlGzWriter,
    validate_record_shapes,
    write_manifest,
)

POLL_SECONDS = 300.0

# Shipped POST /api/analytics/* routes (framework-level; building_id from config only).
ANALYTICS_POST_ROUTES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("/api/analytics/runtime", {}),
    ("/api/analytics/vav-health", {}),
    ("/api/analytics/ahu-health", {}),
    ("/api/analytics/ahu-temperature-health", {}),
    ("/api/analytics/ahu-pressure-health", {}),
    ("/api/analytics/ahu-economizer-health", {}),
    ("/api/analytics/chiller-health", {}),
    ("/api/analytics/cooling-tower-health", {}),
    ("/api/analytics/boiler-health", {}),
    ("/api/analytics/hp-health", {}),
    ("/api/analytics/zone-other-health", {}),
    ("/api/analytics/sensor-health", {}),
    ("/api/analytics/sensor-faults", {}),
    ("/api/analytics/pid-hunting", {}),
    ("/api/analytics/schedule", {}),
    ("/api/analytics/mechanical-cooling", {}),
    ("/api/analytics/bas-vs-web-oat", {}),
    ("/api/analytics/inspect", {}),
    ("/api/analytics/economizer", {}),
    ("/api/analytics/rcx/ahu", {}),
    ("/api/analytics/rcx/vav", {}),
    ("/api/analytics/rcx/chiller", {}),
    ("/api/analytics/rcx/boiler", {}),
    ("/api/analytics/rcx/preset", {"series": {"preset_id": "economizer_deltas"}}),
    ("/api/analytics/metering", {}),
    ("/api/analytics/mv", {}),
    ("/api/analytics/fuel", {}),
    ("/api/analytics/setpoints", {}),
    ("/api/analytics/diurnal", {}),
)

TELEMETRY_TABLES = ("sample", "point_map", "authorized_series")


def load_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        out[key] = value
        os.environ.setdefault(key, value)
    return out


def load_sites_config(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sites = doc.get("sites") if isinstance(doc, dict) else doc
    if not isinstance(sites, list) or not sites:
        raise SystemExit(f"sites config must be a non-empty list: {path}")
    for index, site in enumerate(sites):
        if not isinstance(site, dict) or not str(site.get("building_id", "")).strip():
            raise SystemExit(f"sites[{index}] needs building_id")
    return sites


def load_rule_registry() -> list[dict[str, Any]]:
    import yaml

    reg_path = REPO / "sql" / "fdd" / "registry.yaml"
    doc = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    rules = doc.get("rules") or []
    if len(rules) < 70:
        raise SystemExit(f"registry.yaml expected ~77 rules, found {len(rules)}")
    return rules


def default_output_dir(shortsha: str) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    sha = shortsha.removeprefix("sha-")[:7] or "local"
    home = Path(os.path.expanduser("~"))
    return home / "openfdd-si-cutover" / f"baseline-{sha}-{day}"


def health_shortsha(http, headers: dict[str, str]) -> str:
    body = http.get_json("/api/health", headers=headers)
    version = str(body.get("version") or body.get("semver") or "")
    if "+" in version:
        return version.split("+", 1)[1]
    return str(body.get("shortsha") or body.get("git_sha") or "local")


def db_connect():
    try:
        import psycopg
    except ImportError:
        return None
    url = (
        os.environ.get("OPENFDD_DATABASE_URL")
        or os.environ.get("OPENFDD_TEST_DATABASE_URL")
        or ""
    ).strip()
    if not url:
        return None
    return psycopg.connect(url)


def telemetry_row_counts(conn, building_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in TELEMETRY_TABLES:
            cur.execute(
                f"SELECT COUNT(*)::bigint FROM {table} WHERE site_id = %s",
                (building_id,),
            )
            counts[table] = int(cur.fetchone()[0])
    return counts


def fetch_sql_daily_rows(
    conn,
    *,
    building_id: str,
    window_start: str,
    window_end: str,
) -> list[dict[str, Any]]:
    """Roll UTC-hour ``fdd_interval_result`` buckets up to UTC calendar days."""
    sql = """
        SELECT rule_id, equipment_id, bucket_start, fault_seconds, covered_seconds
        FROM fdd_interval_result
        WHERE site_id = %s
          AND bucket_start >= %s::timestamptz
          AND bucket_start < %s::timestamptz
        ORDER BY rule_id, equipment_id, bucket_start
    """
    daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (building_id, window_start, window_end))
        for rule_id, equipment_id, bucket_start, fault_s, covered_s in cur.fetchall():
            utc_day = bucket_start.astimezone(timezone.utc).date().isoformat()
            key = (rule_id, equipment_id, utc_day)
            slot = daily.setdefault(
                key,
                {
                    "building_id": building_id,
                    "rule_id": rule_id,
                    "equipment_id": equipment_id,
                    "utc_day": utc_day,
                    "fault_seconds": 0.0,
                    "covered_seconds": 0.0,
                    "status": "OK",
                },
            )
            slot["fault_seconds"] += float(fault_s or 0)
            slot["covered_seconds"] += float(covered_s or 0)
    return list(daily.values())


def fetch_run_status_rows(
    conn,
    *,
    building_id: str,
    run_id: str,
) -> dict[tuple[str, str], str]:
    sql = """
        SELECT rule_id, equipment_id, status
        FROM fdd_run
        WHERE site_id = %s AND detail->>'run_id' = %s
    """
    out: dict[tuple[str, str], str] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (building_id, run_id))
        for rule_id, equipment_id, status in cur.fetchall():
            out[(rule_id, equipment_id)] = str(status or "")
    return out


def merge_status(
    daily_rows: list[dict[str, Any]], status_map: dict[tuple[str, str], str]
) -> None:
    for row in daily_rows:
        key = (row["rule_id"], row["equipment_id"])
        row["status"] = status_map.get(key, row.get("status", "OK"))


def resolve_w2c_source_unit(
    *,
    overlay_unit: str | None,
    tag_unit: str | None,
    column_unit: str | None,
    package_unit_system: str | None,
) -> str:
    for candidate in (overlay_unit, tag_unit, column_unit):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return str(package_unit_system or "").strip() or "imperial"


def unit_inventory_rows(
    http,
    headers: dict[str, str],
    *,
    building_id: str,
) -> list[dict[str, Any]]:
    mapping = http.get_json(
        "/api/csv/import/package/mapping",
        headers=headers,
        params={"building_id": building_id},
    )
    package_unit_system = ""
    session = mapping.get("session_config") if isinstance(mapping, dict) else {}
    if isinstance(session, dict):
        package_unit_system = str(session.get("unit_system") or "")
    columns = mapping.get("columns") if isinstance(mapping, dict) else []
    if not isinstance(columns, list):
        columns = []
    conn = db_connect()
    sample_units: dict[str, str] = {}
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT openfdd_key, max(unit) AS unit
                FROM sample
                WHERE site_id = %s
                GROUP BY openfdd_key
                """,
                (building_id,),
            )
            for key, unit in cur.fetchall():
                if key and unit:
                    sample_units[str(key)] = str(unit)
        conn.close()
    rows: list[dict[str, Any]] = []
    for col in columns:
        if not isinstance(col, dict):
            continue
        openfdd_key = str(col.get("openfdd_key") or col.get("column") or "").strip()
        if not openfdd_key:
            continue
        role = str(col.get("role") or col.get("fdd_role") or "").strip()
        point_map_unit = str(col.get("unit") or col.get("point_map_unit") or "").strip()
        overlay_unit = str(col.get("overlay_unit") or col.get("engineer_unit") or "").strip()
        tag_unit = str(col.get("tag_unit") or col.get("nf_unit") or "").strip()
        column_unit = str(col.get("column_unit") or col.get("csv_unit") or "").strip()
        rows.append(
            {
                "building_id": building_id,
                "openfdd_key": openfdd_key,
                "role": role,
                "point_map_unit": point_map_unit,
                "sample_unit": sample_units.get(openfdd_key, ""),
                "package_unit_system": package_unit_system,
                "w2c_source_unit": resolve_w2c_source_unit(
                    overlay_unit=overlay_unit or None,
                    tag_unit=tag_unit or None,
                    column_unit=column_unit or None,
                    package_unit_system=package_unit_system or None,
                ),
            }
        )
    return rows


def analytics_rows_for_site(
    http,
    headers: dict[str, str],
    *,
    building_id: str,
    window_start: str | None,
    window_end: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, extra in ANALYTICS_POST_ROUTES:
        payload: dict[str, Any] = {"building_id": building_id, "refresh": True}
        if window_start:
            payload["window_start"] = window_start
        if window_end:
            payload["window_end"] = window_end
        payload.update(extra)
        try:
            body = analytics_post(http, headers, path, payload)
        except RuntimeError as exc:
            out.append(
                {
                    "building_id": building_id,
                    "endpoint": path,
                    "row": {"error": str(exc), "ok": False},
                }
            )
            continue
        envelope = body.get("analytics") if isinstance(body.get("analytics"), dict) else body
        rows = []
        if isinstance(envelope, dict):
            for key in ("rows", "points", "equipment", "series", "data"):
                val = envelope.get(key)
                if isinstance(val, list) and val:
                    rows = val
                    break
        if not rows and isinstance(envelope, dict) and envelope:
            rows = [envelope]
        if not rows:
            rows = [{"note": "empty", "ok": body.get("ok")}]
        for row in rows[:500]:
            if isinstance(row, dict):
                out.append({"building_id": building_id, "endpoint": path, "row": row})
    return out


def _utc_day_key(ts) -> str:
    if hasattr(ts, "astimezone"):
        return ts.astimezone(timezone.utc).date().isoformat()
    return str(ts)[:10]


def pandas_daily_rows(
    http,
    headers: dict[str, str],
    *,
    building_id: str,
    rules: list[dict[str, Any]],
    window_start: str,
    window_end: str,
    max_rules: int | None = None,
) -> list[dict[str, Any]]:
    from importlib.util import find_spec

    if find_spec("open_fdd") is None or find_spec("pandas") is None:
        safe_print("WARN: skip pandas baseline (install pandas and open-fdd[oracle])")
        return []

    import pandas as pd
    from open_fdd.analytics.units import apply_unit_metadata
    from open_fdd.rules import RULES_BY_ID, run_rule

    equipment_body = http.get_json(
        "/api/fdd/equipment",
        headers=headers,
        params={"building_id": building_id},
    )
    equipment = equipment_body.get("equipment") or equipment_body.get("items") or []
    if not isinstance(equipment, list):
        equipment = []

    out: list[dict[str, Any]] = []
    rule_limit = max_rules or len(rules)
    for rule in rules[:rule_limit]:
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id or rule_id not in RULES_BY_ID:
            continue
        if not rule.get("pandas_function"):
            continue
        kinds = rule.get("equipment_kinds") or []
        for equip in equipment[:50]:
            if not isinstance(equip, dict):
                continue
            eid = str(equip.get("equipment_id") or equip.get("id") or "").strip()
            etype = str(equip.get("equip_type") or equip.get("equipment_type") or "").strip()
            if kinds and etype and etype not in kinds:
                continue
            if not eid:
                continue
            try:
                frame = _equipment_frame(http, headers, building_id=building_id, equipment_id=eid)
            except (RuntimeError, ValueError):
                continue
            if frame.empty:
                continue
            apply_unit_metadata(frame, {"unit_system": "imperial"})
            start = pd.Timestamp(window_start, tz="UTC")
            end = pd.Timestamp(window_end, tz="UTC")
            frame = frame.loc[(frame.index >= start) & (frame.index < end)]
            if frame.empty:
                continue
            params = _default_rule_params(rule)
            try:
                result = run_rule(
                    rule_id,
                    frame,
                    params=params,
                    poll_seconds=POLL_SECONDS,
                    require_operational_gates=True,
                )
            except Exception:
                continue
            mask = getattr(result, "confirmed_fault", None)
            if mask is None:
                continue
            daily_fault = _fault_seconds_by_utc_day(mask, poll_seconds=POLL_SECONDS)
            status = str(getattr(result, "status", "OK"))
            for utc_day, fault_seconds in daily_fault.items():
                out.append(
                    {
                        "building_id": building_id,
                        "rule_id": rule_id,
                        "equipment_id": eid,
                        "utc_day": utc_day,
                        "fault_seconds": fault_seconds,
                        "status": status,
                    }
                )
    return out


def _default_rule_params(rule: dict[str, Any]) -> dict[str, float]:
    params: dict[str, float] = {}
    for name, spec in (rule.get("parameters") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            try:
                params[name] = float(spec["default"])
            except (TypeError, ValueError):
                continue
    return params


def _equipment_frame(http, headers, *, building_id: str, equipment_id: str):
    import pandas as pd

    from helpers import mint_opaque_point_iri, point_resolve, post_sparql

    pts = post_sparql(
        http,
        headers,
        building_id=building_id,
        query_id="fdd_role_candidates",
        equipment_id=equipment_id,
    )
    series: dict[str, pd.Series] = {}
    for pt in pts:
        if not isinstance(pt, dict):
            continue
        col = str(pt.get("column") or pt.get("pointId") or "").strip()
        role = str(pt.get("fddSelection") or pt.get("canonicalRole") or col).strip()
        if not col or not role:
            continue
        iri = mint_opaque_point_iri(building_id, equipment_id, col)
        body = point_resolve(http, headers, point_iri=iri, include_history=True, max_points=5000)
        hist = body.get("history") if isinstance(body.get("history"), dict) else {}
        samples = hist.get("samples") or []
        if not samples:
            continue
        idx = pd.to_datetime([s["ts"] for s in samples], utc=True)
        vals = [s.get("val") for s in samples]
        series[role] = pd.Series(vals, index=idx, name=role)
    if not series:
        raise ValueError("no series")
    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs.update(
        equipment_id=equipment_id,
        building_id=building_id,
        unit_system="imperial",
    )
    return df


def _fault_seconds_by_utc_day(mask, *, poll_seconds: float) -> dict[str, float]:
    import pandas as pd

    if mask is None or len(mask) == 0:
        return {}
    aligned = mask.fillna(False).astype(bool)
    deltas = aligned.index.to_series().diff().dt.total_seconds()
    out: dict[str, float] = defaultdict(float)
    for i in range(1, len(aligned)):
        if not aligned.iloc[i - 1]:
            continue
        dt = float(deltas.iloc[i]) if pd.notna(deltas.iloc[i]) else poll_seconds
        if dt <= 0 or dt > poll_seconds * 2:
            dt = poll_seconds
        day = _utc_day_key(aligned.index[i - 1])
        out[day] += dt
    return dict(out)


def capture_site(
    http,
    headers: dict[str, str],
    *,
    site: dict[str, Any],
    out_dir: Path,
    rules: list[dict[str, Any]],
    skip_pandas: bool,
    pandas_max_rules: int | None,
) -> dict[str, Any]:
    building_id = str(site["building_id"]).strip()
    window_start = str(site.get("window_start") or site.get("start") or "").strip() or None
    window_end = str(site.get("window_end") or site.get("end") or "").strip() or None

    conn_before = db_connect()
    counts_before: dict[str, int] | None = None
    if conn_before is not None:
        counts_before = telemetry_row_counts(conn_before, building_id)

    run_body: dict[str, Any] = {
        "mode": "registry",
        "building_id": building_id,
        "force_new_data": True,
    }
    if window_start:
        run_body["window_start"] = window_start
    if window_end:
        run_body["window_end"] = window_end
    run_resp = http.post_json("/api/fdd/run", headers=headers, json_body=run_body)
    if not run_resp.get("ok", True) and run_resp.get("error"):
        raise RuntimeError(f"/api/fdd/run failed: {run_resp.get('error')}")

    run_id = str(run_resp.get("run_id") or "")
    ws = str(run_resp.get("window_start") or window_start or "")
    we = str(run_resp.get("window_end") or window_end or "")

    sql_daily: list[dict[str, Any]] = []
    conn = db_connect()
    if conn is not None and ws and we:
        sql_daily = fetch_sql_daily_rows(
            conn, building_id=building_id, window_start=ws, window_end=we
        )
        if run_id:
            merge_status(
                sql_daily,
                fetch_run_status_rows(conn, building_id=building_id, run_id=run_id),
            )
        conn.close()
    else:
        safe_print(
            "WARN: OPENFDD_DATABASE_URL unset — SQL daily rows come from /api/fdd/run results only"
        )
        for row in run_resp.get("results") or []:
            if not isinstance(row, dict):
                continue
            sql_daily.append(
                {
                    "building_id": building_id,
                    "rule_id": str(row.get("rule_id") or ""),
                    "equipment_id": str(row.get("equipment_id") or ""),
                    "utc_day": ws[:10] if ws else "",
                    "fault_seconds": int(float(row.get("fault_hours") or 0) * 3600),
                    "covered_seconds": 0,
                    "status": str(row.get("status") or "OK"),
                }
            )

    analytics = analytics_rows_for_site(
        http, headers, building_id=building_id, window_start=ws or None, window_end=we or None
    )
    units = unit_inventory_rows(http, headers, building_id=building_id)
    pandas_rows: list[dict[str, Any]] = []
    if not skip_pandas and ws and we:
        pandas_rows = pandas_daily_rows(
            http,
            headers,
            building_id=building_id,
            rules=rules,
            window_start=ws,
            window_end=we,
            max_rules=pandas_max_rules,
        )

    sample_counts: list[dict[str, Any]] = []
    conn_after = db_connect()
    if conn_after is not None:
        counts_after = telemetry_row_counts(conn_after, building_id)
        for table in TELEMETRY_TABLES:
            sample_counts.append(
                {"building_id": building_id, "table": table, "row_count": counts_after[table]}
            )
        if counts_before is not None and counts_before != counts_after:
            raise RuntimeError(
                f"telemetry row counts changed for {building_id}: "
                f"before={counts_before} after={counts_after}"
            )
        conn_after.close()

    site_dir = out_dir / building_id
    site_dir.mkdir(parents=True, exist_ok=True)
    with JsonlGzWriter(site_dir / "sql_fdd_daily.jsonl.gz") as writer:
        for row in sql_daily:
            writer.write(row)
    with JsonlGzWriter(site_dir / "analytics_rows.jsonl.gz") as writer:
        for row in analytics:
            writer.write(row)
    with JsonlGzWriter(site_dir / "pandas_fdd_daily.jsonl.gz") as writer:
        for row in pandas_rows:
            writer.write(row)
    with JsonlGzWriter(site_dir / "unit_inventory.jsonl.gz") as writer:
        for row in units:
            writer.write(row)
    with JsonlGzWriter(site_dir / "sample_counts.jsonl.gz") as writer:
        for row in sample_counts:
            writer.write(row)
    persisted = [
        {
            "building_id": building_id,
            "run_id": run_id,
            "window_start": ws,
            "window_end": we,
        }
    ]
    with JsonlGzWriter(site_dir / "persisted_runs.jsonl.gz") as writer:
        for row in persisted:
            writer.write(row)

    return {
        "building_id": building_id,
        "run_id": run_id,
        "sql_rows": len(sql_daily),
        "analytics_rows": len(analytics),
        "pandas_rows": len(pandas_rows),
        "unit_rows": len(units),
    }


def emit_ip_goldens(
    out_dir: Path,
    *,
    golden_dir: Path,
    site_summaries: list[dict[str, Any]],
) -> None:
    golden_dir.mkdir(parents=True, exist_ok=True)
    for summary in site_summaries:
        building_id = summary["building_id"]
        site_dir = out_dir / building_id
        golden: dict[str, Any] = {"building_id": building_id, "schema": "si-cutover-ip-golden-v1"}
        for name in (
            "sql_fdd_daily.jsonl.gz",
            "analytics_rows.jsonl.gz",
            "pandas_fdd_daily.jsonl.gz",
        ):
            path = site_dir / name
            if not path.is_file():
                continue
            import gzip

            rows = []
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            golden[name.removesuffix(".jsonl.gz")] = rows
        out_path = golden_dir / f"{building_id}.json"
        out_path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_self_test() -> int:
    records = {
        "sql_fdd_daily": [
            {
                "building_id": "SYNTH_SELFTEST",
                "rule_id": "FC1",
                "equipment_id": "AHU_1",
                "utc_day": "2026-06-01",
                "fault_seconds": 120.0,
                "covered_seconds": 3600.0,
                "status": "FAULT",
            }
        ],
        "analytics_rows": [
            {
                "building_id": "SYNTH_SELFTEST",
                "endpoint": "/api/analytics/economizer",
                "row": {"ok": True},
            }
        ],
        "pandas_fdd_daily": [
            {
                "building_id": "SYNTH_SELFTEST",
                "rule_id": "FC1",
                "equipment_id": "AHU_1",
                "utc_day": "2026-06-01",
                "fault_seconds": 120.0,
                "status": "FAULT",
            }
        ],
        "unit_inventory": [
            {
                "building_id": "SYNTH_SELFTEST",
                "openfdd_key": "AHU_1.fan_status",
                "role": "fan-status",
                "point_map_unit": "1",
                "sample_unit": "1",
                "package_unit_system": "imperial",
                "w2c_source_unit": "imperial",
            }
        ],
        "sample_counts": [
            {"building_id": "SYNTH_SELFTEST", "table": "sample", "row_count": 10},
        ],
        "persisted_runs": [
            {
                "building_id": "SYNTH_SELFTEST",
                "run_id": "run-selftest",
                "window_start": "2026-06-01T00:00:00Z",
                "window_end": "2026-06-02T00:00:00Z",
            }
        ],
    }
    errors = validate_record_shapes(records)
    if errors:
        for err in errors:
            safe_print(f"FAIL self-test: {err}")
        return 1
    safe_print("PASS capture_ip_baseline --self-test shapes")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_connection_args(ap)
    ap.add_argument("--jwt-env", type=Path, help="dotenv file with API base URL and credentials")
    ap.add_argument("--sites-config", type=Path, help="JSON list of sites (building_id, window)")
    ap.add_argument("--output-dir", type=Path, help="Override ~/openfdd-si-cutover/baseline-…")
    ap.add_argument("--skip-pandas", action="store_true", help="Skip pandas IP recompute")
    ap.add_argument(
        "--pandas-max-rules",
        type=int,
        default=0,
        help="Limit pandas rules (0 = all registry rules with pandas twins)",
    )
    ap.add_argument("--self-test", action="store_true", help="Offline JSON shape validation")
    ap.add_argument(
        "--emit-ip-goldens",
        type=Path,
        metavar="DIR",
        help="Write tests/fixtures/si_cutover/ip_goldens/*.json from capture output",
    )
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.jwt_env or not args.sites_config:
        ap.error("--jwt-env and --sites-config are required unless --self-test")

    load_dotenv_file(args.jwt_env.expanduser())
    sites = load_sites_config(args.sites_config.expanduser())
    rules = load_rule_registry()
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    pandas_cap = args.pandas_max_rules if args.pandas_max_rules > 0 else None

    summaries: list[dict[str, Any]] = []
    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        shortsha = health_shortsha(http, headers)
        out_dir = args.output_dir or default_output_dir(shortsha)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_print(f"baseline output: {out_dir}")
        for site in sites:
            safe_print(f"capture site {site.get('building_id')}")
            summaries.append(
                capture_site(
                    http,
                    headers,
                    site=site,
                    out_dir=out_dir,
                    rules=rules,
                    skip_pandas=args.skip_pandas,
                    pandas_max_rules=pandas_cap,
                )
            )
        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "health_shortsha": shortsha,
            "base_url": base,
            "sites": summaries,
        }
        write_manifest(out_dir, meta=meta)
        if args.emit_ip_goldens:
            emit_ip_goldens(out_dir, golden_dir=args.emit_ip_goldens, site_summaries=summaries)

    safe_print(f"PASS capture — {len(summaries)} site(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
