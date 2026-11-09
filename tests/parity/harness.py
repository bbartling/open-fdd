"""pandas == SQL parity harness (SI only).

SQL side: ``tests/parity/sql_run.mjs`` runs the pack (nf-app/rules/pack-*.json) on PGlite (real Postgres) and
sql.js (SQLite) over a deterministic SI dataset (nf-app/hooks/lib/synthetic_dataset.js).
pandas side: the same dataset, renamed to Haystack roles, through ``open_fdd.rules`` for every SQL rule that
has a pandas twin (same rule id). Nothing here converts units: every value is SI.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from open_fdd.rules import RULES_BY_ID  # noqa: E402
from open_fdd.rules.base import hours_true  # noqa: E402
from open_fdd.rules.runner import run_cookbook_rule  # noqa: E402

ROLE_MAP = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
CATALOG = {r["rule_id"]: r for r in json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]}

# SQL history column -> pandas Haystack role. Columns the role map does not name keep their SQL name.
SQL_TO_HS = {**ROLE_MAP, "web_oa_t": "web-outside-air-temp", "web_oa_dp": "web-outside-air-dewpoint",
             "web_wb_t": "web-outside-air-wetbulb"}
HS_TO_SQL = {v: k for k, v in SQL_TO_HS.items()}

# SQL rule id -> pandas rule id where they differ
PANDAS_ID = {"FC13-SAT-HIGH": "FC13"}

# Compared fault-hour tolerance: both sides integrate forward sample holds on a gap-free 5-minute grid,
# so equal rules agree to floating-point noise.
ABS_TOL_H = 1e-6


def node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("node is required for the SQL side (nf-app engines)")
    return exe


def run_sql(equips: int, days: int, out: Path, engines: str = "pglite,sqlite", rules: str = "") -> dict:
    """Run the SQL pack on the engines; return the parsed JSON (also left on disk at ``out``)."""
    cmd = [node(), str(HERE / "sql_run.mjs"), "--equips", str(equips), "--days", str(days), "--out", str(out),
           "--engines", engines]
    if rules:
        cmd += ["--rules", rules]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"sql_run.mjs failed:\n{proc.stdout}\n{proc.stderr}")
    data = json.loads(out.read_text(encoding="utf-8"))
    data["wall_s"] = time.time() - t0
    return data


def equip_frame(data: dict, equip: str) -> pd.DataFrame:
    h = data["history"][equip]
    idx = pd.DatetimeIndex(pd.to_datetime(h["ts"], unit="ms", utc=True), name="timestamp_utc")
    cols = {}
    for c in data["columns"]:
        name = c["name"]
        v = h.get(name)
        if v is None:
            continue
        s = pd.Series(v, index=idx)
        cols[SQL_TO_HS.get(name, name)] = pd.to_numeric(s, errors="coerce") if c["type"] != "text" else s
    df = pd.DataFrame(cols, index=idx)
    # an all-NULL column is a missing role (SQL carries it as typed NULL); weather may then supply web_* roles
    df = df.loc[:, df.notna().any()]
    # keep SQL-named duplicates out: only roles pandas knows plus anything unmapped
    df.attrs["equipment_id"] = equip
    df.attrs["role_units"] = {SQL_TO_HS.get(k, k): u for k, u in data["units"].items() if u}
    return df


def weather_frame(data: dict) -> pd.DataFrame | None:
    rows = data.get("weather") or []
    if not rows:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in rows], unit="ms", utc=True))
    out = pd.DataFrame({"web-outside-air-temp": [r.get("web_oa_t") for r in rows],
                        "web-outside-air-dewpoint": [r.get("web_oa_dp") for r in rows]}, index=idx)
    # SQL joins weather as-of (last sample carried forward up to cadence + margin = 25 min); mirror that on the grid
    step = pd.Timedelta(seconds=data["meta"]["step_seconds"])
    grid = pd.date_range(out.index[0], out.index[-1], freq=step)
    return out.reindex(out.index.union(grid)).ffill(limit=int(25 * 60 / data["meta"]["step_seconds"])).reindex(grid)


def sql_rows(data: dict, engine: str, rule: str) -> dict[str, dict]:
    """Rows by equipment, retaining per-role sweep scores and the legacy max aggregate."""
    rows = data["results"].get(engine, {}).get(rule) or []
    if not any("sensor_role" in row for row in rows):
        return {r["equipment_id"]: r for r in rows}
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["equipment_id"], []).append(row)
    out = {}
    for equip, group in grouped.items():
        by_role = {}
        for row in group:
            role = row.get("sensor_role")
            if role is not None and row.get("fault_hours") is not None:
                by_role[role] = max(float(row["fault_hours"]), by_role.get(role, float("-inf")))
        out[equip] = {"equipment_id": equip, "fault_hours": max(by_role.values(), default=None),
                      "sensor_fault_hours": by_role}
    return out


def sql_result_key(row: dict) -> tuple[str, str]:
    """Stable ordering for equipment-level rules and newly per-role sensor sweeps."""
    return (row.get("equipment_id", ""), row.get("sensor_role", ""))


def pandas_rule_result(rule_id: str, df: pd.DataFrame, weather):
    rule = RULES_BY_ID[PANDAS_ID.get(rule_id, rule_id)]
    kind = rule.equipment_kinds[0] if rule.equipment_kinds else "ahu"
    df.attrs["equipment_type"] = kind.upper()  # type-dispatched proofs (mechanical cooling, ...) need it
    confirm_min = (CATALOG[rule_id]["parameters"].get("confirm_min") or {}).get("default", 0.0)
    params = {"confirm_min": confirm_min}
    res = run_cookbook_rule(rule, df.copy(), equipment_id=df.attrs["equipment_id"], equipment_kind=kind,
                            poll_seconds=300.0, params_by_rule={rule.id: params}, weather=None if weather is None else weather.copy(),
                            require_operational_gates=True)
    if res.status == "PASS":
        return 0.0, "PASS", res
    if res.confirmed_fault is not None and res.status == "FAULT":
        # full precision: RuleResult.fault_hours is rounded to 2 decimals for display
        return hours_true(res.confirmed_fault, 300.0), "FAULT", res
    return res.fault_hours, str(res.status), res


def pandas_fault_hours(rule_id: str, df: pd.DataFrame, weather) -> tuple[float | None, str]:
    """Compatibility wrapper used by debug_rule.py and older parity helpers."""
    hours, status, _ = pandas_rule_result(rule_id, df, weather)
    return hours, status


def compare(data: dict, only: set[str] | None = None) -> dict:
    """Compare pandas fault hours with SQL fault hours for every rule that has both."""
    equips = list(data["history"])
    weather = weather_frame(data)
    sql_rules = sorted(CATALOG)
    twins = [r for r in sql_rules if PANDAS_ID.get(r, r) in RULES_BY_ID]
    no_twin = [r for r in sql_rules if PANDAS_ID.get(r, r) not in RULES_BY_ID]
    report = {"compared": {}, "no_twin": no_twin, "twins": twins, "engines_agree": {}}
    for rule in twins:
        if only and rule not in only:
            continue
        per = {}
        for e in equips:
            row = sql_rows(data, "pglite", rule).get(e)
            if row is None or row.get("fault_hours") is None:
                continue
            try:
                # fresh frame per run: rules stash evidence/units in df.attrs and must not leak into each other
                ph, status, pandas_result = pandas_rule_result(rule, equip_frame(data, e), weather)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                ph, status, pandas_result = None, f"ERROR {type(exc).__name__}: {exc}", None
            item = {"sql": float(row["fault_hours"]), "pandas": None if ph is None else float(ph), "status": status}
            if "sensor_fault_hours" in row:
                evidence = (pandas_result.metrics.get("sv_sweep_evidence") or []) if pandas_result else []
                oracle_roles = {
                    HS_TO_SQL.get(r["role"], r["role"]): float(r["fault_hours"])
                    for r in evidence
                    if r.get("role") is not None and r.get("fault_hours") is not None
                }
                oracle_silence = {
                    HS_TO_SQL.get(r["role"], r["role"]): float(r["silence_hours"])
                    for r in evidence
                    if r.get("role") is not None and r.get("silence_hours") is not None
                }
                sql_roles = row["sensor_fault_hours"]
                item["sql_sensor_fault_hours"] = sql_roles
                item["pandas_sensor_fault_hours"] = oracle_roles
                item["pandas_sensor_silence_hours"] = oracle_silence
                # Existing equipment-level convention is the worst sensor, not the union of faulted time.
                if oracle_roles:
                    item["pandas"] = max(oracle_roles.values())
                else:
                    item["pandas"] = 0.0
            per[e] = item
        if per:
            report["compared"][rule] = per
    return report


def rule_matches(per: dict) -> bool:
    for v in per.values():
        sql_roles = v.get("sql_sensor_fault_hours")
        pandas_roles = v.get("pandas_sensor_fault_hours")
        if sql_roles is not None or pandas_roles is not None:
            if sql_roles is None or pandas_roles is None or set(sql_roles) != set(pandas_roles):
                return False
            # Oracle evidence is intentionally rounded to 0.001 hours for reporting.
            if any(abs(float(sql_roles[r]) - float(pandas_roles[r])) > 0.0005 + 1e-6 * abs(float(sql_roles[r]))
                   for r in sql_roles):
                return False
        p = v["pandas"]
        if p is None:
            if v["sql"] > ABS_TOL_H:
                return False
            continue
        role_tol = 0.0005 + 1e-6 * abs(float(v["sql"])) if "sql_sensor_fault_hours" in v else ABS_TOL_H
        if abs(p - v["sql"]) > role_tol:
            return False
    return True


def peak_rss_mb() -> float:
    """Peak resident set of this Python process in MB (Windows: PeakWorkingSetSize; POSIX: ru_maxrss)."""
    if os.name == "nt":
        class _PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(k32.GetCurrentProcess()), ctypes.byref(pmc), pmc.cb)
        return pmc.PeakWorkingSetSize / 1048576
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1048576 if sys.platform == "darwin" else rss / 1024
