"""Execute shipped postgres FDD SQL against CI Timescale for si-cutover goldens."""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.role_candidates import _HAYSTACK_SLUG_TO_ROLE  # noqa: E402

from scripts.stress.si_cutover.capture_ip_baseline import (  # noqa: E402
    daily_fault_and_covered_seconds,
)
from scripts.stress.si_cutover.ci_fixtures_lib import (  # noqa: E402
    frame_column_to_sql_role,
    registry_role_column,
)
from scripts.stress.si_cutover.product_sql_params import (  # noqa: E402
    catalog_overrides_from_registry,
    ip_parameter_controls,
    legacy_param_key,
)
from scripts.stress.si_cutover.si_parity_families import (  # noqa: E402
    W4C_SI_ZONE_FAMILY,
    ahu_econ_si_sql_shipped,
    family_dataset_ids,
    sensor_util_si_sql_shipped,
    sql_si_pack_enabled,
)

PENDING_W4 = "pending_W4"
W4D_PLANT_RULES = frozenset(
    {
        "CHW-NOLOAD-1",
        "CHW-1",
        "CHW-2",
        "CHW-3",
        "CHW-4",
        "CW-OPT-1",
        "CW-APR-1",
        "CW-FAN-1",
        "HP-1",
        "TRIM-1",
        "TRIM-3",
        "TRIM-4",
    }
)
SI_SQL_PACK_AVAILABLE = False  # global flag; W4c zone and W4d plant rules ship per-rule.


def w4c_target_datasets() -> frozenset[str]:
    return family_dataset_ids(W4C_SI_ZONE_FAMILY)


def rule_si_sql_shipped(rule_id: str) -> bool:
    """W4d plant and W4e sensor/utility rules whose P2 cells are computed live per row."""
    return str(rule_id) in W4D_PLANT_RULES or sensor_util_si_sql_shipped(str(rule_id))


def _load_parity_module():
    path = REPO / "scripts" / "timescale" / "test_synthetic_pandas_sql_parity.py"
    spec = importlib.util.spec_from_file_location("ts_parity", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_ui_p0():
    path = REPO / "scripts" / "timescale" / "test_ui_p0_timescale.py"
    spec = importlib.util.spec_from_file_location("ui_p0", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def infer_poll_seconds(index) -> float:
    import pandas as pd

    if len(index) < 2:
        return 300.0
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return 300.0
    sec = float(deltas.median().total_seconds())
    return sec if sec >= 1.0 else 300.0


def haystack_col_to_sql(col: str) -> str:
    if col in _HAYSTACK_SLUG_TO_ROLE:
        return _HAYSTACK_SLUG_TO_ROLE[col]
    token = col.replace("-", "_")
    return token


def frame_sql_columns(frame) -> set[str]:
    cols: set[str] = set()
    for col in frame.columns:
        if col == "occ_mode":
            cols.add("occ_mode")
            continue
        cols.add(frame_column_to_sql_role(str(col)))
    return cols


@lru_cache(maxsize=1)
def _registry_history_column_names() -> frozenset[str]:
    from scripts.stress.si_cutover.ci_fixtures_lib import load_rule_registry

    cols: set[str] = {"equipment_id", "timestamp_utc", "occ_mode"}
    for rule in load_rule_registry():
        for role in list(rule.get("required_roles") or []) + list(rule.get("optional_roles") or []):
            col = registry_role_column(str(role))
            if col == "occ_mode":
                cols.add("occ_mode")
            else:
                cols.add(frame_column_to_sql_role(col))
    return frozenset(cols)


def history_columns_for_rules(frame, rules: list[dict[str, Any]]) -> set[str]:
    """Union frame columns, registry roles, and postgres SQL-referenced history columns."""
    cols = frame_sql_columns(frame)
    for rule in rules:
        for role in list(rule.get("required_roles") or []) + list(rule.get("optional_roles") or []):
            col = registry_role_column(str(role))
            if col == "occ_mode":
                cols.add("occ_mode")
            else:
                cols.add(frame_column_to_sql_role(col))
        sql_file = rule.get("sql_file")
        if not sql_file:
            continue
        path = REPO / "sql" / "fdd" / "postgres" / "rules" / str(sql_file)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for col in _registry_history_column_names():
            if col in ("equipment_id", "timestamp_utc"):
                continue
            if re.search(rf"(?<![a-z0-9_]){re.escape(col)}(?![a-z0-9_])", text):
                cols.add(col)
    return cols


def render_rule_sql(
    rule: dict[str, Any],
    poll_seconds: float,
    *,
    overrides: dict[str, float] | None = None,
    storage: str = "si",
) -> str:
    sys.path.insert(0, str(REPO / "sql" / "fdd"))
    from render_rule import render  # type: ignore

    rule_id = str(rule["rule_id"])
    controls = None
    if storage == "ip":
        controls = ip_parameter_controls(rule_id)
        if controls is not None and overrides:
            # SI-renamed keys (parameter_si_rename_map.json) map back to the
            # base-branch IP control names that ``controls`` is keyed by.
            overrides = {(k if k in controls else legacy_param_key(k)): v for k, v in overrides.items()}
    return render(
        rule_id,
        poll_seconds=poll_seconds,
        overrides=overrides,
        dialect="postgres",
        parameter_controls=controls,
    )


def rewrite_fault_series(sql: str, equipment_id: str) -> str | None:
    ui = _load_ui_p0()
    return ui.rewrite_fault_series(sql, equipment_id)


def purge_site(cur, site_id: str) -> None:
    cur.execute("DELETE FROM sample WHERE site_id = %s", (site_id,))
    cur.execute("DELETE FROM point_map WHERE site_id = %s", (site_id,))
    cur.execute("DELETE FROM role_map WHERE building_id = %s", (site_id,))
    cur.execute("DELETE FROM equipment WHERE building_id = %s", (site_id,))
    cur.execute("DELETE FROM building WHERE building_id = %s", (site_id,))
    cur.execute("DELETE FROM site WHERE site_id = %s", (site_id,))


def default_role_unit(sql_role: str) -> str | None:
    return default_role_unit_storage(sql_role, storage="ip")


def default_role_unit_storage(sql_role: str, *, storage: str) -> str | None:
    si = storage == "si"
    temps = {
        "oa_t",
        "mat",
        "rat",
        "sat",
        "zone_t",
        "chw_supply_t",
        "chw_return_t",
        "hw_supply_t",
        "hw_return_t",
        "cw_supply_t",
        "web_wb_t",
    }
    if sql_role in temps:
        return "degC" if si else "degF"
    if sql_role in ("oa_h", "ra_h", "zone_rh", "ma_h", "sa_h"):
        return "percent"
    if sql_role == "duct_static":
        return "Pa" if si else "inWC"
    if sql_role == "chw_dp":
        return "kPa" if si else "psi"
    if sql_role == "chw_flow":
        return "L_per_s" if si else "gpm"
    if sql_role in ("fan_status", "fan_cmd", "pump_status", "chiller_status"):
        return "bool"
    if sql_role == "zone_flow":
        return "L_per_s" if si else "cfm"
    return None


def seed_frame(
    cur,
    parity,
    *,
    site_id: str,
    equipment_id: str,
    equip_type: str,
    frame,
    storage: str = "ip",
) -> None:
    cur.execute(
        "INSERT INTO site(site_id, dis, timezone, enabled) VALUES (%s, %s, 'UTC', true)",
        (site_id, site_id),
    )
    cur.execute(
        "INSERT INTO building(building_id, site_id, dis, timezone) VALUES (%s, %s, %s, 'UTC')",
        (site_id, site_id, site_id),
    )
    cur.execute(
        "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES (%s, %s, %s)",
        (site_id, equipment_id, equip_type),
    )
    for ts, row in frame.iterrows():
        stamp = ts.to_pydatetime().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for col in frame.columns:
            val = row[col]
            if col == "occ_mode":
                token = str(val).strip().lower()
                fval = (
                    0.0
                    if token
                    in (
                        "unoccupied",
                        "0",
                        "0.0",
                        "false",
                        "off",
                    )
                    else 1.0
                )
                sql_role = "occ_mode"
                openfdd_key = f"{equipment_id}.{sql_role}"
                cur.execute(
                    """
                    INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (stamp, site_id, openfdd_key, openfdd_key, fval),
                )
                parity.bind_current(cur, site_id, equipment_id, sql_role, openfdd_key)
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            sql_role = frame_column_to_sql_role(str(col))
            openfdd_key = f"{equipment_id}.{sql_role}"
            cur.execute(
                """
                INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (stamp, site_id, openfdd_key, openfdd_key, fval),
            )
            parity.bind_current(cur, site_id, equipment_id, sql_role, openfdd_key)
            unit = default_role_unit_storage(sql_role, storage=storage)
            if unit:
                cur.execute(
                    """
                    UPDATE role_map SET unit = %s
                    WHERE building_id = %s AND equipment_id = %s AND openfdd_key = %s AND role = %s
                    """,
                    (unit, site_id, equipment_id, openfdd_key, sql_role),
                )
                # authorized_series projects the unit from point_map (W1a #1406);
                # sensor-sweep SQL masks roles whose bound unit is missing.
                cur.execute(
                    """
                    UPDATE point_map SET unit = %s
                    WHERE site_id = %s AND equipment_id = %s AND openfdd_key = %s AND role = %s
                    """,
                    (unit, site_id, equipment_id, openfdd_key, sql_role),
                )


def fill_history(cur, site_id: str, sql_columns: set[str]) -> None:
    sql_columns = {c for c in sql_columns if c not in ("equipment_id", "timestamp_utc")}
    if not sql_columns:
        sql_columns = {"fan_status"}
    ordered = sorted(sql_columns)
    typed = ", ".join(f"{col} double precision" for col in ordered)
    col_list = ", ".join(ordered)
    filters = ", ".join(
        f"max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{col}')"
        for col in ordered
    )
    cur.execute(
        f"""
        CREATE TEMP TABLE history (
          equipment_id text,
          timestamp_utc timestamptz,
          {typed}
        ) ON COMMIT DROP
        """
    )
    cur.execute(
        f"""
        INSERT INTO history (equipment_id, timestamp_utc, {col_list})
        SELECT split_part(openfdd_key, '.', 1), ts, {filters}
        FROM sample
        WHERE site_id = %s
        GROUP BY 1, 2
        ORDER BY 2
        """,
        (site_id,),
    )


def sql_daily_from_confirmed(
    *,
    building_id: str,
    rule_id: str,
    equipment_id: str,
    confirmed,
    index,
    poll_seconds: float,
    status: str = "OK",
) -> list[dict[str, Any]]:
    import pandas as pd

    fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
        confirmed, index, poll_seconds=poll_seconds
    )
    days = sorted(set(fault_by_day) | set(covered_by_day))
    rows: list[dict[str, Any]] = []
    for day in days:
        rows.append(
            {
                "building_id": building_id,
                "rule_id": rule_id,
                "equipment_id": equipment_id,
                "utc_day": day,
                "fault_seconds": float(fault_by_day.get(day, 0.0)),
                "covered_seconds": float(covered_by_day.get(day, 0.0)),
                "status": status,
                "pair_status": "computed",
                "reason": "",
            }
        )
    return rows


def execute_sql_rule_daily(
    cur,
    *,
    rule: dict[str, Any],
    building_id: str,
    equipment_id: str,
    poll_seconds: float,
    index,
    render_overrides: dict[str, float] | None = None,
    storage: str = "si",
) -> tuple[list[dict[str, Any]], str | None]:
    """Run one postgres rule; return daily rows or (empty, error reason)."""
    import pandas as pd

    rule_id = str(rule.get("rule_id") or "")
    sql_file = rule.get("sql_file")
    if not sql_file:
        return [], "no_sql_file"
    try:
        sql = render_rule_sql(rule, poll_seconds, overrides=render_overrides, storage=storage)
    except Exception as exc:
        return [], f"render: {exc}"

    overlay = rewrite_fault_series(sql, equipment_id)
    if overlay:
        try:
            cur.execute(overlay)
            fetched = cur.fetchall()
        except Exception as exc:
            return [], f"sql overlay: {exc}"
        if not fetched:
            return [], "sql overlay empty"
        ts_list = []
        flags = []
        for _equip, ts, flag in fetched:
            ts = pd.Timestamp(ts)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            ts_list.append(ts)
            flags.append(bool(flag))
        confirmed = pd.Series(flags, index=pd.DatetimeIndex(ts_list)).sort_index()
        return sql_daily_from_confirmed(
            building_id=building_id,
            rule_id=rule_id,
            equipment_id=equipment_id,
            confirmed=confirmed,
            index=index,
            poll_seconds=poll_seconds,
        ), None

    try:
        cur.execute(sql)
        fetched = cur.fetchall()
        columns = [d.name for d in cur.description]
    except Exception as exc:
        return [], f"sql: {exc}"
    if not fetched:
        return [], "sql empty"
    if "fault_hours" not in columns:
        return [], "no fault_hours column"
    equip_idx = columns.index("equipment_id")
    hours_idx = columns.index("fault_hours")
    hours = None
    for row in fetched:
        if str(row[equip_idx]) == equipment_id:
            hours = float(row[hours_idx])
            break
    if hours is None:
        return [], "equipment missing in sql result"
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return [], "bad index"
    days = sorted({ts.date().isoformat() for ts in index})
    if len(days) == 1:
        day = days[0]
        return [
            {
                "building_id": building_id,
                "rule_id": rule_id,
                "equipment_id": equipment_id,
                "utc_day": day,
                "fault_seconds": hours * 3600.0,
                "covered_seconds": float(len(index)) * poll_seconds,
                "status": "FAULT" if hours > 0 else "OK",
                "pair_status": "computed",
                "reason": "",
            }
        ], None
    return [], "aggregate fault_hours spans multiple UTC days; need fault series overlay"


def apply_fdd_postgres_helpers(conn) -> None:
    path = REPO / "sql" / "fdd" / "postgres" / "postgres_helpers.sql"
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def run_sql_ip_for_dataset(
    conn,
    *,
    spec,
    frame,
    equipment_id: str,
    rules: list[dict[str, Any]],
    poll_seconds: float,
    params_by_rule: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    parity = _load_parity_module()
    parity.apply_schema(conn)
    apply_fdd_postgres_helpers(conn)
    site_id = spec.building_id
    sql_cols = history_columns_for_rules(frame, rules)
    errors: list[str] = []
    out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        purge_site(cur, site_id)
        seed_frame(
            cur,
            parity,
            site_id=site_id,
            equipment_id=equipment_id,
            equip_type=spec.equipment_type,
            frame=frame,
        )
        fill_history(cur, site_id, sql_cols)
        for rule in rules:
            rule_id = str(rule.get("rule_id") or "")
            if not rule.get("sql_file"):
                continue
            params = (params_by_rule or {}).get(rule_id) or {}
            render_overrides = catalog_overrides_from_registry(rule, params)
            cur.execute("SAVEPOINT si_cutover_rule")
            daily, err = execute_sql_rule_daily(
                cur,
                rule=rule,
                building_id=site_id,
                equipment_id=equipment_id,
                poll_seconds=poll_seconds,
                index=frame.index,
                render_overrides=render_overrides,
                storage="ip",
            )
            if err:
                cur.execute("ROLLBACK TO SAVEPOINT si_cutover_rule")
                errors.append(f"{rule_id}: {err}")
                continue
            cur.execute("RELEASE SAVEPOINT si_cutover_rule")
            out.extend(daily)
        conn.commit()
    return out, errors


def run_sql_si_for_dataset(
    conn,
    *,
    spec,
    frame,
    equipment_id: str,
    rules: list[dict[str, Any]],
    poll_seconds: float,
    params_by_rule: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run postgres rules against SI-valued history (W4d plant pack)."""
    parity = _load_parity_module()
    parity.apply_schema(conn)
    apply_fdd_postgres_helpers(conn)
    site_id = f"{spec.building_id}__si"
    sql_cols = history_columns_for_rules(frame, rules)
    errors: list[str] = []
    out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        purge_site(cur, site_id)
        seed_frame(
            cur,
            parity,
            site_id=site_id,
            equipment_id=equipment_id,
            equip_type=spec.equipment_type,
            frame=frame,
            storage="si",
        )
        fill_history(cur, site_id, sql_cols)
        for rule in rules:
            rule_id = str(rule.get("rule_id") or "")
            if not rule.get("sql_file"):
                continue
            params = (params_by_rule or {}).get(rule_id) or {}
            render_overrides = catalog_overrides_from_registry(rule, params)
            cur.execute("SAVEPOINT si_cutover_rule")
            daily, err = execute_sql_rule_daily(
                cur,
                rule=rule,
                building_id=spec.building_id,
                equipment_id=equipment_id,
                poll_seconds=poll_seconds,
                index=frame.index,
                render_overrides=render_overrides,
                storage="si",
            )
            if err:
                cur.execute("ROLLBACK TO SAVEPOINT si_cutover_rule")
                errors.append(f"{rule_id}: {err}")
                continue
            cur.execute("RELEASE SAVEPOINT si_cutover_rule")
            out.extend(daily)
        conn.commit()
    return out, errors


def p2_pair_for_si_row(
    *,
    rule_id: str,
    equipment_id: str,
    utc_day: str,
    pandas_si_fault_seconds: float | None,
    pandas_si_missing: bool = False,
    sql_si_fault_seconds: float | None = None,
) -> dict[str, Any]:
    if sql_si_pack_enabled(rule_id):
        return {
            "rule_id": rule_id,
            "equipment_id": equipment_id,
            "utc_day": utc_day,
            "sql_si_fault_seconds": sql_si_fault_seconds,
            "pandas_si_fault_seconds": None if pandas_si_missing else pandas_si_fault_seconds,
            "pandas_si_status": "missing_si_cell" if pandas_si_missing else "computed",
            "sql_si_status": "computed" if sql_si_fault_seconds is not None else PENDING_W4,
        }
    if rule_si_sql_shipped(rule_id) or ahu_econ_si_sql_shipped(rule_id):
        if pandas_si_missing or sql_si_fault_seconds is None:
            return {
                "rule_id": rule_id,
                "equipment_id": equipment_id,
                "utc_day": utc_day,
                "sql_si_fault_seconds": None,
                "pandas_si_fault_seconds": None if pandas_si_missing else pandas_si_fault_seconds,
                "pandas_si_status": "missing_si_cell" if pandas_si_missing else "computed",
                "sql_si_status": "pending_sql_si",
            }
        return {
            "rule_id": rule_id,
            "equipment_id": equipment_id,
            "utc_day": utc_day,
            "sql_si_fault_seconds": float(sql_si_fault_seconds),
            "pandas_si_fault_seconds": float(pandas_si_fault_seconds),
            "sql_si_status": "computed",
        }
    if SI_SQL_PACK_AVAILABLE:
        return {
            "rule_id": rule_id,
            "equipment_id": equipment_id,
            "utc_day": utc_day,
            "sql_si_fault_seconds": pandas_si_fault_seconds,
            "pandas_si_fault_seconds": pandas_si_fault_seconds,
            "sql_si_status": "computed",
        }
    return {
        "rule_id": rule_id,
        "equipment_id": equipment_id,
        "utc_day": utc_day,
        "sql_si_fault_seconds": None,
        "pandas_si_fault_seconds": None if pandas_si_missing else pandas_si_fault_seconds,
        "pandas_si_status": "missing_si_cell" if pandas_si_missing else "computed",
        "sql_si_status": PENDING_W4,
    }
