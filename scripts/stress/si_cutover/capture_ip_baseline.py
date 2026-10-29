#!/usr/bin/env python3
"""Read-only IP baseline capture for the 4.0.7 SI cutover (#1284).

Writes FDD results only, never telemetry: ``POST /api/fdd/run`` with
``force_new_data: true`` persists ``fdd_run`` / ``fdd_interval_result``, and
analytics calls use ``refresh: true`` (``analytics_result`` cache). Those derived
stores may grow. Telemetry tables ``sample``, ``point_map``, and
``authorized_series`` must not change — the capture aborts if their row counts
drift.

For each configured site (JWT env file + sites JSON — no site names in code):
  * SQL IP FDD: fault/covered seconds and status per rule × equipment × UTC day
    (bulk ``POST /api/fdd/run``, then ``fdd_interval_result`` UTC-hour buckets
    rolled up to UTC calendar days via ``OPENFDD_DATABASE_URL``)
  * Analytics: every shipped ``POST /api/analytics/*`` row (no truncation)
  * Pandas IP: every registry rule × site equipment with explicit
    ``pair_status`` (``computed``, ``not_applicable``, ``no_pandas_function``,
    ``error``) and daily ``fault_seconds`` / ``covered_seconds`` when computed
  * Unit inventory with W2c-style source unit (or ``unresolved`` — never a silent
    default)
  * Sample row counts + sha256 manifest under ``~/openfdd-si-cutover/baseline-<sha>-<date>/``

``OPENFDD_DATABASE_URL`` or ``--database-url`` is mandatory for capture mode.
Compose ``.env`` often points at the Timescale **container** hostname; on the
host running this script use the published port, for example
``postgresql://openfdd:PASSWORD@127.0.0.1:5432/openfdd`` (match user/db from
``.env`` / ``OPENFDD_TIMESCALE_PASSWORD``).

Login: ``--jwt-env PATH`` loads ``OPENFDD_API_BASE``, ``OPENFDD_AGENT_PASSWORD``,
and related keys into the process (values are never printed). ``--password`` wins
when passed explicitly; otherwise ``login`` uses ``OPENFDD_AGENT_PASSWORD`` from
that file or the environment.

``open_fdd`` + ``pandas`` are mandatory unless ``--skip-pandas``. Host-side DB
access needs ``psycopg[binary]`` (see ``scripts/qualification/requirements.txt``).
Exit non-zero on any ``error`` pair unless ``--allow-errors`` (recorded in the
manifest).

CI: ``--self-test`` (offline shapes); ``--emit-ip-goldens DIR`` for W0c fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
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
    post_sparql,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

from si_cutover.baseline_history import load_samples_in_window  # noqa: E402
from si_cutover.baseline_io import (  # noqa: E402
    JsonlGzWriter,
    validate_record_shapes,
    write_manifest,
)

POLL_SECONDS = 300.0

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


def require_database_url() -> str:
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "Timescale URL required for capture mode: set OPENFDD_DATABASE_URL or "
            "pass --database-url (host example: "
            "postgresql://openfdd:PASSWORD@127.0.0.1:5432/openfdd)"
        )
    return url


def resolve_capture_password(args: argparse.Namespace) -> str | None:
    """Login password after ``--jwt-env`` is loaded; never log or print."""
    if args.password is not None:
        return str(args.password)
    return (
        os.environ.get("OPENFDD_AGENT_PASSWORD")
        or os.environ.get("OPENFDD_STRESS_PASS")
        or os.environ.get("OPENFDD_ADMIN_PASSWORD")
    )


def _pandas_pair_status_from_result(result: Any) -> tuple[str, str] | None:
    """Map non-computed run_rule outcomes to capture pair_status.

    Returns ``None`` when ``confirmed_fault`` is present and daily seconds should
    be rolled up.
    """
    status = str(getattr(result, "status", "OK"))
    if getattr(result, "confirmed_fault", None) is not None:
        return None
    if status == "ERROR":
        return ("error", status)
    applicable = getattr(result, "applicable", True)
    if not applicable or status.startswith("SKIPPED") or status.startswith("NOT_APPLICABLE"):
        reason = "missing_roles" if "MISSING_ROLES" in status else status.lower()
        return ("not_applicable", reason)
    if status.startswith("NOT_ASSESSED"):
        return ("not_applicable", status.lower())
    return ("error", "missing confirmed_fault on result")


def db_connect():
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg is required for capture mode (Timescale SQL reads). Install with: "
            "python3 -m pip install 'psycopg[binary]' "
            "(listed in scripts/qualification/requirements.txt for stress tooling)"
        ) from exc

    return psycopg.connect(require_database_url())


def require_pandas_oracle() -> None:
    from importlib.util import find_spec

    if find_spec("open_fdd") is None or find_spec("pandas") is None:
        raise SystemExit(
            "capture requires pandas and open-fdd[oracle] unless --skip-pandas is set"
        )


def default_output_dir(shortsha: str) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    sha = shortsha.removeprefix("sha-")[:7] or "local"
    return Path(os.path.expanduser("~")) / "openfdd-si-cutover" / f"baseline-{sha}-{day}"


def health_shortsha(http, headers: dict[str, str]) -> str:
    body = http.get_json("/api/health", headers=headers)
    version = str(body.get("version") or body.get("semver") or "")
    if "+" in version:
        return version.split("+", 1)[1]
    return str(body.get("shortsha") or body.get("git_sha") or "local")


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
    for candidate in (overlay_unit, tag_unit, column_unit, package_unit_system):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return "unresolved"


def unit_inventory_rows(
    http,
    headers: dict[str, str],
    conn,
    *,
    building_id: str,
) -> tuple[list[dict[str, Any]], int]:
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
    sample_units: dict[str, str] = {}
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
    rows: list[dict[str, Any]] = []
    unresolved = 0
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
        resolved = resolve_w2c_source_unit(
            overlay_unit=overlay_unit or None,
            tag_unit=tag_unit or None,
            column_unit=column_unit or None,
            package_unit_system=package_unit_system or None,
        )
        if resolved == "unresolved":
            unresolved += 1
        inventory_status = "ok" if role else "no_role"
        rows.append(
            {
                "building_id": building_id,
                "openfdd_key": openfdd_key,
                "role": role,
                "inventory_status": inventory_status,
                "point_map_unit": point_map_unit,
                "sample_unit": sample_units.get(openfdd_key, ""),
                "package_unit_system": package_unit_system,
                "w2c_source_unit": resolved,
            }
        )
    return rows, unresolved


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
        rows: list[Any] = []
        if isinstance(envelope, dict):
            for key in ("rows", "points", "equipment", "series", "data"):
                val = envelope.get(key)
                if isinstance(val, list):
                    rows = val
                    break
        if not rows and isinstance(envelope, dict) and envelope:
            rows = [envelope]
        if not rows:
            rows = [{"note": "empty", "ok": body.get("ok")}]
        for row in rows:
            if isinstance(row, dict):
                out.append({"building_id": building_id, "endpoint": path, "row": row})
    return out


def rule_params_from_registry(rule: dict[str, Any]) -> dict[str, float]:
    params: dict[str, float] = {}
    for name, spec in (rule.get("parameters") or {}).items():
        if not isinstance(spec, dict) or "default" not in spec:
            continue
        try:
            params[name] = float(spec["default"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"rule {rule.get('rule_id')}: bad default for parameter {name!r}: {exc}"
            ) from exc
    return params


def daily_fault_and_covered_seconds(
    confirmed_mask,
    sample_index,
    *,
    poll_seconds: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Eligible-hold seconds per UTC day — mirrors ``open_fdd.rules.base.hours_true``.

    SQL ``fdd_interval_result`` fault/covered seconds come from the product FDD
    bucket writer (``services/central/src/fdd_registry_persist.rs`` distributes
    run totals into UTC-hour buckets). The pandas oracle uses the same eligible
    forward-hold semantics as ``hours_true`` for fault hours; we convert to
    seconds and roll up to UTC calendar days for P0 comparison.
    """
    import pandas as pd
    from open_fdd.rules.base import _eligible_hold_seconds

    confirmed = confirmed_mask.reindex(sample_index).fillna(False).astype(bool)
    all_true = pd.Series(True, index=sample_index)
    fault_days: dict[str, float] = {}
    covered_days: dict[str, float] = {}
    if not isinstance(sample_index, pd.DatetimeIndex):
        from open_fdd.rules.base import hours_true

        fault_days[""] = hours_true(confirmed, poll_seconds) * 3600.0
        covered_days[""] = hours_true(all_true, poll_seconds) * 3600.0
        return fault_days, covered_days
    held = _eligible_hold_seconds(sample_index)
    if held is None:
        from open_fdd.rules.base import hours_true

        fault_days[""] = hours_true(confirmed, poll_seconds) * 3600.0
        covered_days[""] = hours_true(all_true, poll_seconds) * 3600.0
        return fault_days, covered_days
    utc_index = sample_index.tz_convert("UTC")
    for i, ts in enumerate(utc_index):
        seconds = float(held.iloc[i])
        if seconds <= 0.0:
            continue
        day_key = ts.date().isoformat()
        covered_days[day_key] = covered_days.get(day_key, 0.0) + seconds
        if bool(confirmed.iloc[i]):
            fault_days[day_key] = fault_days.get(day_key, 0.0) + seconds
    return fault_days, covered_days


def equipment_frame_from_db(
    conn,
    http,
    headers,
    *,
    building_id: str,
    equipment_id: str,
    window_start: str,
    window_end: str,
    equipment_type: str = "",
) -> Any:
    import pandas as pd

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
        role = str(pt.get("fddSelection") or pt.get("canonicalRole") or "").strip()
        if not col:
            continue
        if not role:
            raise ValueError(f"no_role for point column {col!r} on equipment {equipment_id}")
        openfdd_key = str(pt.get("openfdd_key") or f"{equipment_id}.{col}").strip()
        samples = load_samples_in_window(
            conn,
            site_id=building_id,
            openfdd_key=openfdd_key,
            window_start=window_start,
            window_end=window_end,
        )
        if not samples:
            continue
        idx = pd.to_datetime([ts for ts, _ in samples], utc=True)
        vals = [val for _, val in samples]
        series[role] = pd.Series(vals, index=idx, name=role)
    if not series:
        raise ValueError(f"no historian samples for equipment {equipment_id} in window")
    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs.update(
        equipment_id=equipment_id,
        building_id=building_id,
        unit_system="imperial",
    )
    etype = str(equipment_type or "").strip()
    if etype:
        df.attrs["equipment_type"] = etype
        df.attrs["equipType"] = etype
    return df


def _pair_base(building_id: str, rule_id: str, equipment_id: str) -> dict[str, Any]:
    return {
        "building_id": building_id,
        "rule_id": rule_id,
        "equipment_id": equipment_id,
        "utc_day": "",
        "fault_seconds": 0.0,
        "covered_seconds": 0.0,
        "status": "",
        "pair_status": "",
        "reason": "",
    }


def collect_pandas_fdd_rows(
    http,
    headers: dict[str, str],
    conn,
    *,
    building_id: str,
    rules: list[dict[str, Any]],
    window_start: str,
    window_end: str,
    pandas_max_rules: int | None,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    from open_fdd.analytics.units import stamp_display_units
    from open_fdd.rules import RULES_BY_ID, run_rule

    import pandas as pd

    equipment_body = http.get_json(
        "/api/fdd/equipment",
        headers=headers,
        params={"building_id": building_id},
    )
    equipment = equipment_body.get("equipment") or equipment_body.get("items") or []
    if not isinstance(equipment, list):
        equipment = []

    if pandas_max_rules is not None:
        rules_iter = rules[:pandas_max_rules]
    else:
        rules_iter = rules

    out: list[dict[str, Any]] = []
    coverage: Counter[str] = Counter()
    error_messages: list[str] = []

    for rule in rules_iter:
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        kinds = rule.get("equipment_kinds") or []
        for equip in equipment:
            if not isinstance(equip, dict):
                continue
            eid = str(equip.get("equipment_id") or equip.get("id") or "").strip()
            etype = str(equip.get("equip_type") or equip.get("equipment_type") or "").strip()
            if not eid:
                continue
            base = _pair_base(building_id, rule_id, eid)
            if kinds and etype and etype not in kinds:
                out.append(
                    {
                        **base,
                        "pair_status": "not_applicable",
                        "reason": "equipment_type",
                    }
                )
                coverage["not_applicable"] += 1
                continue
            if rule_id not in RULES_BY_ID:
                out.append(
                    {
                        **base,
                        "pair_status": "not_applicable",
                        "reason": "unknown_rule",
                    }
                )
                coverage["not_applicable"] += 1
                continue
            if not rule.get("pandas_function"):
                out.append({**base, "pair_status": "no_pandas_function", "reason": ""})
                coverage["no_pandas_function"] += 1
                continue
            try:
                params = rule_params_from_registry(rule)
                frame = equipment_frame_from_db(
                    conn,
                    http,
                    headers,
                    building_id=building_id,
                    equipment_id=eid,
                    window_start=window_start,
                    window_end=window_end,
                    equipment_type=etype,
                )
            except Exception as exc:
                msg = f"{rule_id}/{eid}: {exc}"
                error_messages.append(msg)
                out.append({**base, "pair_status": "error", "reason": str(exc)})
                coverage["error"] += 1
                continue
            stamp_display_units(frame, {"unit_system": "imperial"})
            start = pd.Timestamp(window_start, tz="UTC")
            end = pd.Timestamp(window_end, tz="UTC")
            frame = frame.loc[(frame.index >= start) & (frame.index < end)]
            if frame.empty:
                out.append(
                    {
                        **base,
                        "pair_status": "not_applicable",
                        "reason": "empty_window",
                    }
                )
                coverage["not_applicable"] += 1
                continue
            try:
                result = run_rule(
                    rule_id,
                    frame,
                    params=params,
                    poll_seconds=POLL_SECONDS,
                    require_operational_gates=True,
                )
            except Exception as exc:
                msg = f"{rule_id}/{eid}: run_rule: {exc}"
                error_messages.append(msg)
                out.append({**base, "pair_status": "error", "reason": str(exc)})
                coverage["error"] += 1
                continue
            mapped = _pandas_pair_status_from_result(result)
            if mapped is not None:
                pair_status, reason = mapped
                out.append(
                    {
                        **base,
                        "pair_status": pair_status,
                        "reason": reason,
                        "status": str(getattr(result, "status", "")),
                    }
                )
                coverage[pair_status] += 1
                if pair_status == "error":
                    error_messages.append(f"{rule_id}/{eid}: {reason}")
                continue
            confirmed = result.confirmed_fault
            status = str(getattr(result, "status", "OK"))
            fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
                confirmed, frame.index, poll_seconds=POLL_SECONDS
            )
            days = sorted(set(fault_by_day) | set(covered_by_day))
            if not days:
                out.append(
                    {
                        **base,
                        "pair_status": "computed",
                        "reason": "",
                        "status": status,
                    }
                )
            else:
                for day in days:
                    out.append(
                        {
                            **base,
                            "utc_day": day,
                            "fault_seconds": fault_by_day.get(day, 0.0),
                            "covered_seconds": covered_by_day.get(day, 0.0),
                            "pair_status": "computed",
                            "reason": "",
                            "status": status,
                        }
                    )
            coverage["computed"] += 1
    return out, dict(coverage), error_messages


def capture_site(
    http,
    headers: dict[str, str],
    conn,
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

    counts_before = telemetry_row_counts(conn, building_id)

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
    if not ws or not we:
        raise RuntimeError("FDD run returned no window_start/window_end")

    sql_daily = fetch_sql_daily_rows(
        conn, building_id=building_id, window_start=ws, window_end=we
    )
    if run_id:
        merge_status(
            sql_daily,
            fetch_run_status_rows(conn, building_id=building_id, run_id=run_id),
        )

    analytics = analytics_rows_for_site(
        http, headers, building_id=building_id, window_start=ws, window_end=we
    )
    units, unresolved_units = unit_inventory_rows(
        http, headers, conn, building_id=building_id
    )

    pandas_rows: list[dict[str, Any]] = []
    pandas_coverage: dict[str, int] = {}
    pandas_errors: list[str] = []
    if skip_pandas:
        pandas_coverage = {"skipped": 1}
    else:
        pandas_rows, pandas_coverage, pandas_errors = collect_pandas_fdd_rows(
            http,
            headers,
            conn,
            building_id=building_id,
            rules=rules,
            window_start=ws,
            window_end=we,
            pandas_max_rules=pandas_max_rules,
        )

    counts_after = telemetry_row_counts(conn, building_id)
    sample_counts = [
        {"building_id": building_id, "table": table, "row_count": counts_after[table]}
        for table in TELEMETRY_TABLES
    ]
    if counts_before != counts_after:
        raise RuntimeError(
            f"telemetry row counts changed for {building_id}: "
            f"before={counts_before} after={counts_after}"
        )

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
        "unresolved_units": unresolved_units,
        "pandas_coverage": pandas_coverage,
        "pandas_errors": pandas_errors,
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
                "covered_seconds": 3600.0,
                "status": "FAULT",
                "pair_status": "computed",
                "reason": "",
            }
        ],
        "unit_inventory": [
            {
                "building_id": "SYNTH_SELFTEST",
                "openfdd_key": "AHU_1.fan_status",
                "role": "fan-status",
                "inventory_status": "ok",
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
    for action in ap._actions:
        if action.dest == "password":
            action.default = None
            break
    ap.add_argument(
        "--database-url",
        default=None,
        help="Timescale URL for host-side capture (overrides OPENFDD_DATABASE_URL)",
    )
    ap.add_argument(
        "--jwt-env",
        type=Path,
        help="dotenv file with OPENFDD_API_BASE, OPENFDD_AGENT_PASSWORD, etc.",
    )
    ap.add_argument("--sites-config", type=Path, help="JSON list of sites (building_id, window)")
    ap.add_argument("--output-dir", type=Path, help="Override ~/openfdd-si-cutover/baseline-…")
    ap.add_argument("--skip-pandas", action="store_true", help="Skip pandas IP recompute")
    ap.add_argument(
        "--pandas-max-rules",
        type=int,
        default=0,
        help="If >0, limit pandas rules to first N in registry (recorded in manifest)",
    )
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="Do not exit non-zero when any rule×equipment pair_status is error",
    )
    ap.add_argument("--self-test", action="store_true", help="Offline JSON shape validation")
    ap.add_argument(
        "--emit-ip-goldens",
        type=Path,
        metavar="DIR",
        help="Write tests/fixtures/si_cutover/ip_goldens/*.json from capture output",
    )
    ap.add_argument(
        "--ci-fixtures-emit-goldens",
        type=Path,
        metavar="DIR",
        help="Offline: emit ip goldens from cookbook + SYNTH CI fixtures (no stack)",
    )
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.ci_fixtures_emit_goldens:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from si_cutover.ci_fixtures_lib import emit_all_goldens

        url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not url:
            raise SystemExit("--ci-fixtures-emit-goldens requires OPENFDD_DATABASE_URL")
        paths = emit_all_goldens(args.ci_fixtures_emit_goldens, database_url=url)
        safe_print(f"PASS ci-fixtures emit — {len(paths)} golden(s) → {args.ci_fixtures_emit_goldens}")
        return 0

    if not args.jwt_env or not args.sites_config:
        ap.error("--jwt-env and --sites-config are required unless --self-test")

    load_dotenv_file(args.jwt_env.expanduser())
    if args.database_url:
        os.environ["OPENFDD_DATABASE_URL"] = str(args.database_url).strip()
    require_database_url()
    if not args.skip_pandas:
        require_pandas_oracle()

    sites = load_sites_config(args.sites_config.expanduser())
    rules = load_rule_registry()
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    pandas_cap = args.pandas_max_rules if args.pandas_max_rules > 0 else None

    summaries: list[dict[str, Any]] = []
    all_errors: list[str] = []
    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=resolve_capture_password(args))
        shortsha = health_shortsha(http, headers)
        out_dir = args.output_dir or default_output_dir(shortsha)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_print(f"baseline output: {out_dir}")
        with db_connect() as conn:
            for site in sites:
                safe_print(f"capture site {site.get('building_id')}")
                summary = capture_site(
                    http,
                    headers,
                    conn,
                    site=site,
                    out_dir=out_dir,
                    rules=rules,
                    skip_pandas=args.skip_pandas,
                    pandas_max_rules=pandas_cap,
                )
                summaries.append(summary)
                all_errors.extend(summary.get("pandas_errors") or [])
        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "health_shortsha": shortsha,
            "base_url": base,
            "skip_pandas": args.skip_pandas,
            "pandas_max_rules": pandas_cap,
            "allow_errors": args.allow_errors,
            "sites": summaries,
        }
        write_manifest(out_dir, meta=meta)
        if args.emit_ip_goldens:
            emit_ip_goldens(out_dir, golden_dir=args.emit_ip_goldens, site_summaries=summaries)

    if all_errors and not args.allow_errors:
        safe_print(f"FAIL capture — {len(all_errors)} pandas pair error(s)")
        for msg in all_errors[:20]:
            safe_print(f"  {msg}")
        return 1
    safe_print(f"PASS capture — {len(summaries)} site(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
