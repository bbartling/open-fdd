"""pandas == SQL parity harness (SI only): thin repo-side glue over ``open_fdd.parity``.

Dataset:  ``open_fdd.parity.generate`` (a bit-exact port of nf-app/tests/fixtures/synthetic_dataset.js; see
          test_generator_equivalence.py).
SQL side: ``adapters.NodeEngineAdapter`` runs the pack (nf-app/rules/pack-*.json) on PGlite (real Postgres) and sql.js
          (SQLite) through ``sql_run.mjs``.
pandas:   ``open_fdd.parity.pandas_ref`` runs ``open_fdd.rules``; ``open_fdd.parity.compare`` applies the policy.
Nothing here converts units: every value is SI. ``data`` dicts returned by ``run_sql`` carry the ``Dataset`` as
``data["dataset"]``.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import open_fdd.parity.pandas_ref as _reference_mod  # noqa: E402
from adapters import NodeEngineAdapter  # noqa: E402
from open_fdd.parity import Policy, generate, reference  # noqa: E402
from open_fdd.parity import compare as _compare  # noqa: E402
from open_fdd.parity.policy import rule_matches as _rule_matches  # noqa: E402
from open_fdd.parity.policy import sql_result_key, sql_rows_by_equipment  # noqa: E402,F401
from open_fdd.parity.pandas_ref import PANDAS_ID, role_map  # noqa: E402,F401
from open_fdd.rules import RULES_BY_ID  # noqa: E402,F401

ROLE_MAP = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
CATALOG = {r["rule_id"]: r for r in json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))["rules"]}
SQL_TO_HS = role_map()
HS_TO_SQL = {v: k for k, v in SQL_TO_HS.items()}

# Compared fault-hour tolerance: both sides integrate forward sample holds on a gap-free 5-minute grid,
# so equal rules agree to floating-point noise.
ABS_TOL_H = Policy().abs_tol_h


def run_sql(equips: int, days: int, out: Path, engines: str = "pglite,sqlite", rules: str = "",
            duplicate_role: bool = False, rule_sql: dict | None = None, plant_sensors: bool = False,
            profile: str = "basic", seed: int = 0) -> dict:
    """Run the SQL pack on the engines over ``generate(seed, equips, days, profile)``.

    Returns ``{"dataset", "results": {engine: {rule: rows}}, "errors", "timing", "memory", "history", "units", ...}``
    (``history`` columnar, for scale checks) and leaves a JSON summary at ``out``.
    """
    ds = generate(seed, equips, days, profile, duplicate_role=duplicate_role, plant_sensors=plant_sensors)
    t0 = time.time()
    results, errors, timing, memory = {}, {}, {}, {}
    rule_ids = [r for r in rules.split(",") if r] or None
    for kind in engines.split(","):
        ad = NodeEngineAdapter(kind)
        ad.load(ds)
        try:
            results[kind] = ad.run(rule_ids, rule_sql=rule_sql if kind == "pglite" else None)
            raw = ad.raw
        finally:
            ad.close()
        errors.update(raw["errors"])
        timing.update(raw["timing"])
        memory.update(raw["memory"])
    cols = [c["name"] for c in ds.history_columns]
    history: dict[str, dict] = {}
    for row in ds.history:
        h = history.setdefault(row["equipment_id"], {"ts": []})
        h["ts"].append(row["ts"])
        for c in cols:
            h.setdefault(c, []).append(row.get(c))
    data = {"dataset": ds, "meta": {"equips": equips, "days": days, "step_seconds": ds.step_seconds,
                                    "rows": len(ds.history), "columns": len(cols)},
            "columns": ds.history_columns, "history": history, "weather": ds.weather, "units": ds.units,
            "results": results, "errors": errors, "timing": timing, "memory": memory, "wall_s": time.time() - t0}
    out.write_text(json.dumps({k: v for k, v in data.items() if k not in ("dataset", "history", "weather")}), encoding="utf-8")
    return data


def equip_frame(data: dict, equip: str) -> pd.DataFrame:
    return _reference_mod.equip_frame(data["dataset"], equip)


def weather_frame(data: dict):
    return _reference_mod.weather_frame(data["dataset"])


def sql_rows(data: dict, engine: str, rule: str) -> dict[str, dict]:
    """Rows by equipment, aggregating duplicate series by the original oracle role."""
    return sql_rows_by_equipment(data["results"].get(engine, {}).get(rule))


def pandas_rule_result(rule_id: str, df: pd.DataFrame, weather):
    return _reference_mod.pandas_rule_result(rule_id, df, weather)


def pandas_fault_hours(rule_id: str, df: pd.DataFrame, weather) -> tuple[float | None, str]:
    """Compatibility wrapper used by debug_rule.py and the regression fixtures."""
    hours, status, _ = pandas_rule_result(rule_id, df, weather)
    return hours, status


def compare(data: dict, only: set[str] | None = None, policy: Policy | None = None) -> dict:
    """Compare pandas fault hours with SQL fault hours for every rule that has both (pglite results)."""
    twins, no_twin = _reference_mod.twin_rule_ids()
    ref = reference(data["dataset"], rules=only)
    verdict = _compare(data["results"]["pglite"], ref, policy or Policy())
    return {"compared": verdict.per_rule, "no_twin": no_twin, "twins": twins, "verdict": verdict, "reference": ref}


def rule_matches(per: dict) -> bool:
    return _rule_matches(per, Policy())


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
