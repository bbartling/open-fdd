"""Role limits (open_fdd/data/sensor_sweep_limits.json): the SQL render and the pandas sweep read one SI source (#1581).

Runs SV-RANGE on PGlite over the synthetic dataset with the plant sensors switched on (chw_flow L/s, chw_dp Pa,
cw_supply_t / cw_return_t degC, chiller_power kW) and compares per-role fault hours with the pandas oracle.
"""
from __future__ import annotations

import copy
import json
import sys

import pytest

import harness as h

ROOT = h.ROOT
sys.path.insert(0, str(ROOT / "sql" / "fdd"))
import render_rule  # noqa: E402
from open_fdd.rules import sensor_sweep_catalog as cat  # noqa: E402

PLANT_SQL_ROLES = ("chw_flow", "chw_dp", "cw_supply_t", "cw_return_t", "chiller_power")
LIMITS_FILE = ROOT / "open_fdd" / "data" / "sensor_sweep_limits.json"


def _run(tmp_path, name, limits=None):
    rule_sql = {"SV-RANGE": render_rule.render("SV-RANGE", role_limits=limits)} if limits is not None else None
    return h.run_sql(2, 3, tmp_path / f"{name}.json", engines="pglite", rules="SV-RANGE", plant_sensors=True, rule_sql=rule_sql)


def _per_role(data, equip, limits=None):
    """(sql, pandas) fault hours by SQL role name for one equipment."""
    sql = h.sql_rows(data, "pglite", "SV-RANGE")[equip]["sensor_fault_hours"]
    df = h.equip_frame(data, equip)
    if limits is not None:
        df.attrs["sweep_limits"] = limits
    _, _, res = h.pandas_rule_result("SV-RANGE", df, h.weather_frame(data))
    pandas = {h.HS_TO_SQL.get(r["role"], r["role"]): float(r["fault_hours"]) for r in res.metrics["sv_sweep_evidence"]}
    return sql, pandas


def _assert_same(data, limits=None):
    for equip in data["history"]:
        sql, pandas = _per_role(data, equip, limits)
        assert set(sql) == set(pandas), (equip, sorted(set(sql) ^ set(pandas)))
        for role in sql:
            assert sql[role] == pytest.approx(pandas[role], abs=h.ABS_TOL_H), (equip, role, sql[role], pandas[role])


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("limits_default"), "default")


def test_plant_roles_are_assessed_and_healthy_at_the_conservative_defaults(default_run):
    for equip in default_run["history"]:
        sql, pandas = _per_role(default_run, equip)
        assert {"chw_flow", "chw_dp", "chiller_power"} <= set(sql)
        # the condenser-water points of the dataset are sparse (silence faults, same on both sides); the others are in range
        assert all(sql[r] == 0.0 for r in ("chw_flow", "chw_dp", "chiller_power")), sql
    _assert_same(default_run)


def test_override_changes_sql_and_pandas_identically(default_run, tmp_path):
    doc = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    for entry in doc["roles"]:
        if entry["role"] == "chw-flow":
            entry.update(lo=-1.0, hi=15.0)  # the dataset's CHW flow runs 11.4 .. 26.5 L/s
        if entry["role"] == "zone-air-temp":
            entry.update(lo=10.0, hi=22.0)
        if entry["role"] == "chiller-power":
            entry.update(lo=-1.0, hi=90.0)  # 65 .. 135 kW
    limits = cat.load_role_limits(copy.deepcopy(doc))
    assert render_rule.render("SV-RANGE", role_limits=limits) != render_rule.render("SV-RANGE")
    data = _run(tmp_path, "override", limits)
    changed = set()
    for equip in data["history"]:
        sql, _ = _per_role(data, equip, limits)
        base, _ = _per_role(default_run, equip)
        changed |= {r for r in sql if sql[r] != base[r]}
    assert {"chw_flow", "zone_t", "chiller_power"} <= changed  # the override reached the SQL result, not only its text
    _assert_same(data, limits)


def test_chw_flow_out_of_range_faults_in_sql_and_pandas(tmp_path):
    doc = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    next(e for e in doc["roles"] if e["role"] == "chw-flow").update(lo=-1.0, hi=20.0)
    limits = cat.load_role_limits(doc)
    data = _run(tmp_path, "chw_flow", limits)
    for equip in data["history"]:
        sql, pandas = _per_role(data, equip, limits)
        assert sql["chw_flow"] > 0.0 and pandas["chw_flow"] > 0.0
        assert sql["chw_flow"] == pytest.approx(pandas["chw_flow"], abs=h.ABS_TOL_H)
