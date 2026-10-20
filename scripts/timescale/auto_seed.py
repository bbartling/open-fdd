#!/usr/bin/env python3
"""Faster Wave-X seed using COPY + column_map → SQL roles.

Compose-init only — not product runtime. The central image has no Python, so an
empty database is also copied by `services/central/src/starter_seed.rs`. Both
paths set `seed_meta.building50_seed = ok` and neither deletes rows. A full
wipe stays `purge_historian.py` / `OPENFDD_RESET_DB`.
Maps package column_map.json through warehouse role_map.json so openfdd_key
uses warehouse SQL roles (sat/mat/fan_status/…), not raw vendor headers.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path

import psycopg

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from data_safe import env_flag_on, refuse_message, seed_action  # noqa: E402

URL = os.environ.get(
    "OPENFDD_DATABASE_URL",
    "postgresql://openfdd:openfdd_dev_only@127.0.0.1:5432/openfdd",
)
B50 = Path(os.environ.get("OPENFDD_SEED_BUILDING50_DIR", "/seeds/BUILDING_50"))
SQL_ROOT = Path(os.environ.get("OPENFDD_SQL_ROOT", "/sql"))
WAREHOUSE = Path(os.environ.get("OPENFDD_SEED_WAREHOUSE_DIR", "/seeds/warehouse"))
FORCE = os.environ.get("OPENFDD_SEED_FORCE", "0").lower() in {"1", "true", "yes"}


def load_registry(conn) -> int:
    reg = SQL_ROOT / "fdd" / "registry.yaml"
    if not reg.is_file():
        reg = WAREHOUSE / "sql" / "registry.yaml"
    text = reg.read_text(encoding="utf-8") if reg.is_file() else ""
    rules, current = [], None
    for line in text.splitlines():
        if line.strip().startswith("- rule_id:"):
            if current:
                rules.append(current)
            current = {"rule_id": line.split(":", 1)[1].strip()}
        elif current is not None and line.strip().startswith("sql_file:"):
            current["sql_file"] = line.split(":", 1)[1].strip()
    if current:
        rules.append(current)
    n = 0
    with conn.cursor() as cur:
        for r in rules:
            if not r.get("rule_id") or not r.get("sql_file"):
                continue
            cur.execute(
                """
                INSERT INTO fdd_rule_registry(rule_id, sql_file, title, enabled)
                VALUES (%s,%s,%s,true)
                ON CONFLICT (rule_id) DO UPDATE SET sql_file=EXCLUDED.sql_file
                """,
                (r["rule_id"], r["sql_file"], r["rule_id"]),
            )
            n += 1
    conn.commit()
    return n


def load_maps():
    cmap = {}
    p = B50 / "column_map.json"
    if p.is_file():
        cmap = json.loads(p.read_text(encoding="utf-8"))
    role_path = WAREHOUSE / "role_map.json"
    if not role_path.is_file():
        role_path = SQL_ROOT / "fdd" / "role_map.json"
    sql_to_hs = {}
    if role_path.is_file():
        sql_to_hs = json.loads(role_path.read_text(encoding="utf-8"))
    hs_to_sql = {v: k for k, v in sql_to_hs.items()}
    return cmap, hs_to_sql


def csv_to_sql_roles(equipment_id: str, cmap: dict, hs_to_sql: dict) -> dict[str, str]:
    """Return {csv_column: sql_role} for equipment."""
    eq = (cmap.get("equipment") or {}).get(equipment_id) or {}
    column_roles = eq.get("column_roles") or {}
    # column_roles: haystack-role -> csv column
    out = {}
    for hs_role, csv_col in column_roles.items():
        sql_role = hs_to_sql.get(hs_role) or hs_role.replace("-", "_")
        out[csv_col] = sql_role
    return out


def equip_type_stamp(equipment_id: str, cmap: dict) -> str | None:
    eq = (cmap.get("equipment") or {}).get(equipment_id) or {}
    et = eq.get("equipment_type") or eq.get("equipType") or eq.get("equip_type")
    if isinstance(et, str) and et:
        # Normalize stamps used by Open-FDD registry
        low = et.lower()
        if low in {"ahu", "rtu"}:
            return "ahu"
        if low in {"vav"}:
            return "vav"
        if low in {"chwplant", "chiller", "chw"}:
            return "chwPlant"
        if low in {"boiler", "hwplant"}:
            return "boiler"
        if low in {"weather"}:
            return "weather"
        return low
    return None


def seed_csv(
    conn,
    building_id: str,
    equipment_id: str,
    csv_path: Path,
    col_to_role: dict[str, str],
    equip_type: str | None,
) -> int:
    if not col_to_role:
        print(f"SKIP {equipment_id}: no column_map roles")
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO site(site_id,dis,timezone,enabled) VALUES (%s,%s,'UTC',true) ON CONFLICT DO NOTHING",
            (building_id, building_id),
        )
        cur.execute(
            "INSERT INTO building(building_id,site_id,dis,timezone) VALUES (%s,%s,%s,'UTC') ON CONFLICT DO NOTHING",
            (building_id, building_id, building_id),
        )
        cur.execute(
            """
            INSERT INTO equipment(building_id,equipment_id,equip_type) VALUES (%s,%s,%s)
            ON CONFLICT (building_id,equipment_id) DO UPDATE
              SET equip_type=COALESCE(EXCLUDED.equip_type, equipment.equip_type)
            """,
            (building_id, equipment_id, equip_type),
        )
    buf = io.StringIO()
    writer = csv.writer(buf)
    roles_seen: set[str] = set()
    n = 0
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return 0
        ts_col = next(
            (
                c
                for c in reader.fieldnames
                if c.lower() in {"timestamp_utc", "timestamp", "ts", "time"}
            ),
            None,
        )
        if not ts_col:
            return 0
        for rec in reader:
            ts = rec.get(ts_col)
            if not ts:
                continue
            for csv_col, sql_role in col_to_role.items():
                raw = rec.get(csv_col)
                if raw in (None, ""):
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    continue
                roles_seen.add(sql_role)
                openfdd_key = f"{equipment_id}.{sql_role}"
                writer.writerow([ts, building_id, openfdd_key, equipment_id, val])
                n += 1
    buf.seek(0)
    with conn.cursor() as cur:
        if n:
            with cur.copy(
                "COPY sample (ts, site_id, openfdd_key, haystack_id, val) FROM STDIN WITH (FORMAT csv)"
            ) as copy:
                while True:
                    chunk = buf.read(1024 * 1024)
                    if not chunk:
                        break
                    copy.write(chunk)
        for role in sorted(roles_seen):
            openfdd_key = f"{equipment_id}.{role}"
            cur.execute(
                """
                INSERT INTO role_map(building_id,equipment_id,openfdd_key,role)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING
                """,
                (building_id, equipment_id, openfdd_key, role),
            )
            cur.execute(
                """
                INSERT INTO point_map(site_id,openfdd_key,haystack_id,role,equipment_id)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                """,
                (building_id, openfdd_key, openfdd_key, role, equipment_id),
            )
    conn.commit()
    return n


def main() -> int:
    building_id = "BUILDING_50"
    print("fast seed (mapped roles) connecting", URL.split("@")[-1])
    cmap, hs_to_sql = load_maps()
    allow_destructive = env_flag_on(os.environ.get("OPENFDD_ALLOW_DESTRUCTIVE_DB"))
    with psycopg.connect(URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM seed_meta WHERE key='building50_seed'")
            row = cur.fetchone()
            already_seeded = bool(row and row[0] == "ok")
            cur.execute("SELECT count(*) FROM sample WHERE site_id=%s", (building_id,))
            existing_rows = int(cur.fetchone()[0])
        action = seed_action(already_seeded, existing_rows, FORCE, allow_destructive)
        if action == "registry_only":
            print(
                "already seeded; registry only "
                "(OPENFDD_SEED_FORCE=1 and OPENFDD_ALLOW_DESTRUCTIVE_DB=1 to reload)"
            )
            print("registry", load_registry(conn))
            return 0
        if action == "refuse":
            print(refuse_message(building_id, existing_rows, FORCE), file=sys.stderr)
            return 2
        print("registry", load_registry(conn))
        if action == "delete_then_copy":
            print(
                f"WARNING: deleting existing {building_id} historian rows "
                "(OPENFDD_SEED_FORCE=1 and OPENFDD_ALLOW_DESTRUCTIVE_DB=1)",
                file=sys.stderr,
            )
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sample WHERE site_id=%s", (building_id,))
                cur.execute("DELETE FROM role_map WHERE building_id=%s", (building_id,))
                cur.execute("DELETE FROM point_map WHERE site_id=%s", (building_id,))
                cur.execute("DELETE FROM equipment WHERE building_id=%s", (building_id,))
                cur.execute("DELETE FROM seed_meta WHERE key LIKE 'building50%'")
            conn.commit()
        total = 0
        csvs = sorted(B50.rglob("history_wide.csv")) + sorted(B50.rglob("history.csv"))
        for csv_path in csvs:
            rel = csv_path.relative_to(B50)
            parts = rel.parts
            if parts[0] == "VAV" and len(parts) >= 2:
                equipment_id = parts[1]
            else:
                equipment_id = parts[0]
            col_to_role = csv_to_sql_roles(equipment_id, cmap, hs_to_sql)
            et = equip_type_stamp(equipment_id, cmap)
            n = seed_csv(conn, building_id, equipment_id, csv_path, col_to_role, et)
            print(f"COPY {equipment_id}: {n} roles={sorted(set(col_to_role.values()))}")
            total += n
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO seed_meta(key,value) VALUES ('building50_seed','ok') ON CONFLICT (key) DO UPDATE SET value='ok', updated_at=now()"
            )
            cur.execute(
                "INSERT INTO seed_meta(key,value) VALUES ('building50_samples',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                (str(total),),
            )
            cur.execute(
                "INSERT INTO seed_meta(key,value) VALUES ('building50_role_mode','sql_roles_via_column_map') ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()"
            )
            cur.execute("SELECT count(*) FROM sample WHERE site_id=%s", (building_id,))
            print("sample count", cur.fetchone()[0], "mapped_rows", total)
            cur.execute(
                "SELECT openfdd_key, count(*) FROM sample WHERE site_id=%s AND openfdd_key LIKE %s GROUP BY 1 ORDER BY 1",
                (building_id, "AHU_1.%"),
            )
            print("AHU_1 keys:", cur.fetchall())
            cur.execute("SELECT count(*) FROM fdd_rule_registry")
            print("rules", cur.fetchone()[0])
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
