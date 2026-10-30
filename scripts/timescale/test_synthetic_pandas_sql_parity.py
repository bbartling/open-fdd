#!/usr/bin/env python3
"""Opt-in pandas == Timescale SQL parity for a deterministic synthetic site.

This is the stress check. It is not a boot seed. Central's empty-database
starter copies Building 50 only. This script loads site ``SYNTH_PARITY`` into
whatever ``OPENFDD_DATABASE_URL`` points at, runs FC1 through the same postgres
SQL file central renders, and compares fault hours with
``open_fdd.rules`` (pandas cookbook + ``confirm_fault``).

The frame is fixed: 12 five-minute samples, no randomness. ``AHU_FAULT`` is
low duct static at full fan for every row. Eligible time is the forward delta,
so 11 intervals are one hour minus one sample (the last sample adds nothing).
``AHU_OK`` holds static at setpoint (0.0).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SITE = "SYNTH_PARITY"
POLL_SECONDS = 300.0
SAMPLES = 12
START = datetime(2026, 6, 1, tzinfo=timezone.utc)
FAULT_EQUIPMENT = "AHU_FAULT"
OK_EQUIPMENT = "AHU_OK"
HOUR_TOLERANCE = 1e-6



def fc1_product_params() -> tuple[dict, dict[str, float]]:
    """FC1 registry rule and its imperial (IP) params from registry/tuning catalog defaults.

    The synthetic rows are stored in IP (in. w.c.), so both pandas and the rendered
    SQL use the IP view of the same registry defaults the product renders.
    """
    from scripts.ci import unit_contract_lib as uc
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl

    rule = next((r for r in cfl.load_rule_registry() if r.get("rule_id") == "FC1"), None)
    if rule is None:
        raise SystemExit("FC1 missing from sql/fdd/registry.yaml")
    params_ip, _params_si = cfl.resolve_rule_params_ip_si(rule, uc.load_json(uc.METRIC_UNITS))
    return rule, params_ip


def synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(SAMPLES):
        ts = START + timedelta(seconds=index * int(POLL_SECONDS))
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        for equipment_id, static, setpoint in (
            (FAULT_EQUIPMENT, 0.20, 1.00),
            (OK_EQUIPMENT, 1.00, 1.00),
        ):
            rows.append(
                {
                    "ts": stamp,
                    "equipment_id": equipment_id,
                    "fan_status": 1.0,
                    "fan_cmd": 1.0,
                    "duct_static": static,
                    "duct_static_sp": setpoint,
                }
            )
    return rows


def pandas_fault_hours() -> dict[str, tuple[int, float]]:
    import pandas as pd

    from open_fdd.rules.base import confirm_fault, hours_true
    from open_fdd.rules.cookbook_catalog import fc1

    _rule, params = fc1_product_params()
    confirm_seconds = float(params["confirm_seconds"])
    out: dict[str, tuple[int, float]] = {}
    for equipment_id, static, setpoint in (
        (FAULT_EQUIPMENT, 0.20, 1.00),
        (OK_EQUIPMENT, 1.00, 1.00),
    ):
        frame = pd.DataFrame(
            {
                "duct-static-pressure": [static] * SAMPLES,
                "duct-static-pressure-sp": [setpoint] * SAMPLES,
                "fan-status": [1.0] * SAMPLES,
                "fan-cmd": [1.0] * SAMPLES,
            },
            index=pd.date_range(START, periods=SAMPLES, freq="5min", tz="UTC"),
        )
        raw = fc1(frame, params, POLL_SECONDS)
        confirmed = confirm_fault(
            raw, poll_seconds=POLL_SECONDS, confirm_seconds=confirm_seconds
        )
        flags = int(confirmed.fillna(False).astype(bool).sum())
        hours = float(hours_true(confirmed, POLL_SECONDS))
        out[equipment_id] = (flags, hours)
    return out


def _statements(text: str) -> list[str]:
    current: list[str] = []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            current = []
            if stmt:
                out.append(stmt)
    tail = "\n".join(current).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def apply_schema(conn) -> None:
    schema = ROOT / "sql" / "schema"
    # 05 adds point_map.referenced. 07 is the reader view. Motor and other
    # analytics SQL join it; a database that stops at the wide-history helper
    # cannot run those queries.
    for name in (
        "00_extensions.sql",
        "01_bps_core.sql",
        "02_openfdd_dims.sql",
        "03_wide_history_helper.sql",
        "05_portal_inventory.sql",
        "11_point_map_binding_metadata.sql",
        "07_opaque_series_binding.sql",
    ):
        for stmt in _statements((schema / name).read_text(encoding="utf-8")):
            with conn.cursor() as cur:
                cur.execute(stmt)
        conn.commit()


def bind_current(cur, site: str, equipment_id: str, role: str, openfdd_key: str) -> None:
    """Current point_map + role_map binding. Readers join this; they do not split the key."""
    cur.execute(
        """
        INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, referenced)
        VALUES (%s, %s, %s, %s, %s, true)
        ON CONFLICT (site_id, openfdd_key) DO UPDATE
          SET haystack_id = EXCLUDED.haystack_id,
              role = EXCLUDED.role,
              equipment_id = EXCLUDED.equipment_id,
              referenced = true
        """,
        (site, openfdd_key, openfdd_key, role, equipment_id),
    )
    cur.execute(
        """
        INSERT INTO role_map (building_id, equipment_id, openfdd_key, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
          SET role = EXCLUDED.role
        """,
        (site, equipment_id, openfdd_key, role),
    )


def render_fc1() -> str:
    from scripts.stress.si_cutover.ci_timescale_sql import render_rule_sql
    from scripts.stress.si_cutover.product_sql_params import catalog_overrides_from_registry

    rule, params = fc1_product_params()
    return render_rule_sql(
        rule,
        POLL_SECONDS,
        overrides=catalog_overrides_from_registry(rule, params),
        storage="ip",
    )


def connect_with_retry(database_url: str):
    import psycopg

    last = None
    for _ in range(30):
        try:
            return psycopg.connect(database_url, connect_timeout=3)
        except Exception as err:  # noqa: BLE001 — wait for the CI database
            last = err
            import time

            time.sleep(2)
    raise SystemExit(f"could not connect to Timescale: {last}")


def load_and_query(database_url: str) -> dict[str, float]:
    rows = synthetic_rows()
    with connect_with_retry(database_url) as conn:
        apply_schema(conn)
        with conn.cursor() as cur:
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
            for equipment_id in (FAULT_EQUIPMENT, OK_EQUIPMENT):
                cur.execute(
                    """
                    INSERT INTO equipment(building_id, equipment_id, equip_type)
                    VALUES (%s, %s, 'ahu')
                    """,
                    (SITE, equipment_id),
                )
            for row in rows:
                for role in ("fan_status", "fan_cmd", "duct_static", "duct_static_sp"):
                    openfdd_key = f"{row['equipment_id']}.{role}"
                    cur.execute(
                        """
                        INSERT INTO sample (ts, site_id, openfdd_key, haystack_id, val)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (row["ts"], SITE, openfdd_key, openfdd_key, row[role]),
                    )
                    bind_current(cur, SITE, str(row["equipment_id"]), role, openfdd_key)
            cur.execute(
                """
                CREATE TEMP TABLE history (
                  equipment_id text,
                  timestamp_utc timestamptz,
                  duct_static double precision,
                  duct_static_sp double precision,
                  fan_status double precision,
                  fan_cmd double precision
                ) ON COMMIT DROP
                """
            )
            cur.execute(
                """
                INSERT INTO history (equipment_id, timestamp_utc, duct_static, duct_static_sp, fan_status, fan_cmd)
                SELECT split_part(openfdd_key, '.', 1),
                       ts,
                       max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'duct_static'),
                       max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'duct_static_sp'),
                       max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'fan_status'),
                       max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'fan_cmd')
                FROM sample
                WHERE site_id = %s
                GROUP BY 1, 2
                """,
                (SITE,),
            )
            cur.execute(render_fc1())
            found = {row[0]: float(row[1]) for row in cur.fetchall()}
        conn.commit()
    return found


def check_fixture() -> dict[str, tuple[int, float]]:
    got = pandas_fault_hours()
    expect = {
        FAULT_EQUIPMENT: (SAMPLES, (SAMPLES - 1) * POLL_SECONDS / 3600.0),
        OK_EQUIPMENT: (0, 0.0),
    }
    for equipment_id, (flags, hours) in expect.items():
        got_flags, got_hours = got[equipment_id]
        if got_flags != flags or abs(got_hours - hours) > HOUR_TOLERANCE:
            raise SystemExit(
                f"pandas fixture {equipment_id}: flags {got_flags} hours {got_hours}, "
                f"expected flags {flags} hours {hours}"
            )
    return got


def main() -> int:
    if "--check-fixture" in sys.argv:
        got = check_fixture()
        print("pandas fixture", got)
        return 0
    database_url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not database_url:
        print("OPENFDD_DATABASE_URL is required for the Timescale comparison", file=sys.stderr)
        return 2
    pandas_hours = check_fixture()
    sql_hours = load_and_query(database_url)
    mismatches = []
    for equipment_id, (_flags, hours) in pandas_hours.items():
        sql = sql_hours.get(equipment_id)
        if sql is None or abs(sql - hours) > HOUR_TOLERANCE:
            mismatches.append(f"{equipment_id}: pandas={hours} sql={sql}")
    if mismatches:
        print("FAIL pandas != SQL", *mismatches, sep="\n", file=sys.stderr)
        return 1
    print("OK FC1 pandas == SQL", {k: v[1] for k, v in pandas_hours.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
