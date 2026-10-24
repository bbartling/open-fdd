#!/usr/bin/env python3
"""Timescale checks for the Building 50 UI P0s.

P0-2: starter rules FC1, AHU-SATDEV, AHU-DUCTHI, FAN-RUNTIME-HOURS, FC10,
FC12, and CHW-1 return a numeric pass/fault (or fan runtime) against seeded
rows. A chwPlant stamp stays applicable to CHW-1.

P0-3: FC1 SQL rewrites to a per-sample confirmed_fault series and that series
has at least one true flag for the faulting air handler.

P0-4: motor weekly hours count fan_status, not fan_status plus fan_cmd, so
the air plant_group is not doubled.

This is not a boot seed. It writes only site P0_UI.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = "P0_UI"
POLL = 300
SAMPLES = 12
START = datetime(2026, 6, 1, tzinfo=timezone.utc)
STARTER = (
    "FC1",
    "AHU-SATDEV",
    "AHU-DUCTHI",
    "FAN-RUNTIME-HOURS",
    "FC10",
    "FC12",
    "CHW-1",
)
HISTORY_COLS = (
    "duct_static",
    "duct_static_sp",
    "fan_cmd",
    "fan_status",
    "sat",
    "sat_sp",
    "mat",
    "oa_t",
    "oa_damper_pct",
    "clg_valve_pct",
    "chw_supply_t",
    "chw_return_t",
    "chw_pump_cmd",
    "chiller_status",
    "chiller_current",
    "chiller_amps",
    "chiller_power",
    "chw_flow",
    "pump_status",
)


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_parity():
    path = ROOT / "scripts" / "timescale" / "test_synthetic_pandas_sql_parity.py"
    spec = importlib.util.spec_from_file_location("openfdd_parity", path)
    if spec is None or spec.loader is None:
        die(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(raw: str) -> str:
    token = "".join(ch for ch in raw.lower() if ch.isalnum())
    if token in {"ahu", "rtu", "mau", "doas"}:
        return "ahu"
    if token in {"chiller", "chw", "chwplant"}:
        return "chiller"
    if token in {"boiler", "hwplant"}:
        return "boiler"
    return "unknown"


def displayed_status(stored: str, hours: float, kinds: list[str], stamp: str | None) -> str:
    """Same rule as registry_api_timescale::displayed_result_status."""
    has_stamp = bool(stamp and stamp.strip())
    kind = canonical(stamp) if has_stamp and stamp else "unknown"
    if not kinds:
        applies = True
    elif not has_stamp:
        applies = False
    else:
        applies = any(canonical(item) == kind or item.lower() == kind for item in kinds)
    if not applies:
        return "NOT_APPLICABLE_EQUIPMENT_TYPE"
    if not stored or "NOT_APPLICABLE" in stored.upper():
        return "FAULT" if hours > 0 else "PASS"
    return stored


def rewrite_fault_series(sql: str, equipment_id: str) -> str | None:
    text = sql.strip().rstrip(";")
    lower = text.lower()
    if "final as" not in lower or "from ranked" not in lower or "fault_hours" not in lower:
        return None
    final_at = lower.find("final as")
    select_at = lower.rfind("select")
    if select_at <= final_at or "fault_hours" not in lower[select_at:]:
        return None
    head = text[:select_at]
    head_lower = head.lower()
    rel = head_lower[final_at:].find("final as (")
    if rel >= 0:
        body_start = final_at + rel + len("final as (")
        from_ranked = head_lower[body_start:].find("from ranked")
        final_body = head_lower[body_start : body_start + from_ranked]
        if "timestamp_utc" not in final_body and "equipment_id" in final_body:
            abs_eq = body_start + final_body.find("equipment_id")
            comma = head.find(",", abs_eq)
            if comma >= 0:
                head = head[: comma + 1] + "\n    timestamp_utc," + head[comma + 1 :]
    return (
        f"{head}SELECT equipment_id, timestamp_utc, confirmed AS confirmed_fault\n"
        f"FROM final\nWHERE equipment_id = '{equipment_id}'\nORDER BY timestamp_utc"
    )


def registry_rules() -> dict[str, dict]:
    import yaml

    doc = yaml.safe_load((ROOT / "sql" / "fdd" / "registry.yaml").read_text(encoding="utf-8"))
    return {rule["rule_id"]: rule for rule in doc["rules"]}


def render_sql(rule: dict) -> str:
    path = ROOT / "sql" / "fdd" / "postgres" / "rules" / rule["sql_file"]
    raw = path.read_text(encoding="utf-8")
    params = {
        "POLL_SECONDS": str(POLL),
        "CONFIRM_SECONDS": "300",
        "CONFIRM_ROWS": "1",
        "MODE_DELAY_MIN": "0",
        "MODE_DELAY_ROWS": "0",
        "MODE_DELAY_ROWS_PRECEDING": "0",
        "MAX_GAP_HOURS": "1",
    }
    for spec in (rule.get("parameters") or {}).values():
        key = spec.get("sql_placeholder")
        if key:
            params[str(key)] = str(spec.get("default"))
    for key, value in params.items():
        raw = raw.replace("{{" + key + "}}", value)
    if "{{" in raw:
        start = raw.find("{{")
        die(f"{rule['rule_id']} unrendered placeholder {raw[start:start + 40]}")
    return raw


def seed(cur, parity) -> None:
    cur.execute("DELETE FROM sample WHERE site_id = %s", (SITE,))
    cur.execute("DELETE FROM point_map WHERE site_id = %s", (SITE,))
    cur.execute("DELETE FROM role_map WHERE building_id = %s", (SITE,))
    cur.execute("DELETE FROM equipment WHERE building_id = %s", (SITE,))
    cur.execute("DELETE FROM building WHERE building_id = %s", (SITE,))
    cur.execute("DELETE FROM site WHERE site_id = %s", (SITE,))
    cur.execute(
        "INSERT INTO site(site_id, dis, timezone, enabled) VALUES (%s, %s, 'UTC', true)",
        (SITE, SITE),
    )
    cur.execute(
        "INSERT INTO building(building_id, site_id, dis, timezone) VALUES (%s, %s, %s, 'UTC')",
        (SITE, SITE, SITE),
    )
    cur.execute(
        "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES (%s, 'AHU_1', 'ahu')",
        (SITE,),
    )
    cur.execute(
        """
        INSERT INTO equipment(building_id, equipment_id, equip_type)
        VALUES (%s, 'CHILLER_1', 'chwPlant')
        """,
        (SITE,),
    )
    for index in range(SAMPLES):
        ts = START + timedelta(seconds=index * POLL)
        rows = {
            "AHU_1": {
                "fan_status": 1.0,
                "fan_cmd": 1.0,
                "duct_static": 0.20,
                "duct_static_sp": 1.00,
                "sat": 80.0,
                "sat_sp": 55.0,
                "mat": 70.0,
                "oa_t": 40.0,
                "oa_damper_pct": 0.95,
                "clg_valve_pct": 0.80,
            },
            "CHILLER_1": {
                "chw_supply_t": 44.0,
                "chw_return_t": 46.0,
                "chiller_status": 1.0,
            },
        }
        for equipment_id, values in rows.items():
            for role, val in values.items():
                key = f"{equipment_id}.{role}"
                cur.execute(
                    """
                    INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (ts, SITE, key, key, val),
                )
                parity.bind_current(cur, SITE, equipment_id, role, key)


def fill_history(cur) -> None:
    cols = ", ".join(HISTORY_COLS)
    typed = ", ".join(f"{col} double precision" for col in HISTORY_COLS)
    cur.execute(
        f"""
        CREATE TEMP TABLE history (
          equipment_id text,
          timestamp_utc timestamptz,
          {typed}
        ) ON COMMIT DROP
        """
    )
    filters = ", ".join(
        f"max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{col}')"
        for col in HISTORY_COLS
    )
    cur.execute(
        f"""
        INSERT INTO history (equipment_id, timestamp_utc, {cols})
        SELECT split_part(openfdd_key, '.', 1), ts, {filters}
        FROM sample
        WHERE site_id = %s
        GROUP BY 1, 2
        """,
        (SITE,),
    )


def check_rules(cur, rules: dict[str, dict]) -> None:
    statuses: list[str] = []
    for rule_id in STARTER:
        rule = rules[rule_id]
        sql = render_sql(rule)
        cur.execute(sql)
        fetched = cur.fetchall()
        columns = [desc.name for desc in cur.description]
        if not fetched:
            die(f"{rule_id} returned no rows")
        if rule_id == "FAN-RUNTIME-HOURS":
            hours_idx = columns.index("fan_runtime_hours")
            equip_idx = columns.index("equipment_id")
            ahu = next((row for row in fetched if row[equip_idx] == "AHU_1"), None)
            if ahu is None or float(ahu[hours_idx]) <= 0:
                die(f"FAN-RUNTIME-HOURS expected AHU_1 hours > 0, got {fetched}")
            statuses.append("METRIC")
            continue
        hours_idx = columns.index("fault_hours")
        equip_idx = columns.index("equipment_id")
        kinds = list(rule.get("equipment_kinds") or [])
        stamp = "chwPlant" if rule_id == "CHW-1" else "ahu"
        want = "CHILLER_1" if rule_id == "CHW-1" else "AHU_1"
        match = next((row for row in fetched if row[equip_idx] == want), None)
        if match is None:
            die(f"{rule_id} missing {want}: {fetched}")
        hours = float(match[hours_idx])
        status = displayed_status("NOT_APPLICABLE_EQUIPMENT_TYPE", hours, kinds, stamp)
        statuses.append(status)
        print(f"{rule_id} {want} hours={hours} status={status}")
        if "NOT_APPLICABLE" in status:
            die(f"{rule_id} stayed NOT_APPLICABLE for stamp {stamp}")
    if not any(status in {"PASS", "FAULT", "METRIC"} for status in statuses):
        die(f"starter rules produced no pass/fault/metric rows: {statuses}")
    if statuses.count("NOT_APPLICABLE_EQUIPMENT_TYPE") == len(statuses):
        die("starter rules are all NOT_APPLICABLE")


def check_overlay(cur, rules: dict[str, dict]) -> None:
    sql = rewrite_fault_series(render_sql(rules["FC1"]), "AHU_1")
    if not sql or "confirmed AS confirmed_fault" not in sql:
        die("FC1 did not rewrite to a confirmed_fault series")
    cur.execute(sql)
    flags = [int(flag) for _equip, _ts, flag in cur.fetchall()]
    if not flags or max(flags) < 1:
        die(f"FC1 overlay has no confirmed_fault trues: {flags[:8]}")
    print(f"FC1 overlay confirmed_fault trues={sum(1 for flag in flags if flag)} of {len(flags)}")


def check_motor(cur) -> None:
    sql = (ROOT / "sql" / "analytics" / "postgres" / "queries" / "motor_weekly_runtime.sql").read_text(
        encoding="utf-8"
    )
    # Inline $1..$4. psycopg would treat LIKE '%.role' as its own placeholder.
    site = SITE.replace("'", "''")
    sql = (
        sql.replace("$1", f"'{site}'")
        .replace("$2", "NULL::timestamptz")
        .replace("$3", "NULL::timestamptz")
        .replace("$4", "NULL::text[]")
    )
    cur.execute(sql)
    rows = cur.fetchall()
    columns = [desc.name for desc in cur.description]
    equip_idx = columns.index("equipment_id")
    hours_idx = columns.index("run_hours")
    group_idx = columns.index("plant_group")
    signal_idx = columns.index("signal")
    ahu = [row for row in rows if row[equip_idx] == "AHU_1"]
    if len(ahu) != 1:
        die(f"expected one AHU_1 motor row (status preferred), got {rows}")
    hours = float(ahu[0][hours_idx])
    expected = (SAMPLES - 1) * POLL / 3600.0
    if abs(hours - expected) > 1e-6:
        die(f"motor hours {hours} != {expected} (status+cmd would be {expected * 2})")
    if ahu[0][group_idx] != "air" or ahu[0][signal_idx] != "fan_status":
        die(f"AHU_1 motor row should be air/fan_status, got {ahu[0]}")
    print(f"motor weekly AHU_1 air fan_status hours={hours}")


def main() -> int:
    database_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not database_url:
        die("OPENFDD_DATABASE_URL is required")
    parity = load_parity()
    rules = registry_rules()
    missing = [rule_id for rule_id in STARTER if rule_id not in rules]
    if missing:
        die(f"registry missing {missing}")
    with parity.connect_with_retry(database_url) as conn:
        parity.apply_schema(conn)
        with conn.cursor() as cur:
            seed(cur, parity)
            check_motor(cur)
            fill_history(cur)
            check_rules(cur, rules)
            check_overlay(cur, rules)
        conn.commit()
    print("OK ui p0 timescale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
