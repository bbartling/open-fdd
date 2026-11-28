"""Occupied zone temperature range (5.0.22): the Python twin of shared/zone-band.js.

SI storage / limits / defaults / clamping / the 2 F minimum deadband, the same answers as the JS module, the band reaching
the zone comfort analytics (sql/analytics/zone_comfort.sql {lo} / {hi}) and the zone comfort FDD rules (VAV-1 ZONE_T_LO /
ZONE_T_HI, SCHED-1 comfort_low / comfort_high) in the SQL renderer, the pandas runner and the occupancy document.
An explicit per-rule tuning always wins over the band.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from open_fdd.analytics import zone_band as zb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sql" / "fdd"))
F2C = lambda f: (f - 32) * 5 / 9  # noqa: E731


def test_constants_are_si_limits_65_80_default_70_75_deadband_2f():
    assert zb.LIMIT_LO_C == pytest.approx(18.333333333) and zb.LIMIT_HI_C == pytest.approx(26.666666667)
    assert zb.DEFAULT_LO_C == pytest.approx(21.111111111) and zb.DEFAULT_HI_C == pytest.approx(23.888888889)
    assert zb.MIN_DEADBAND_K == 10 / 9 == pytest.approx(F2C(72) - F2C(70))


@pytest.mark.parametrize("raw", [None, {}, {"lo_c": 22}, {"lo_c": "x", "hi_c": 24}, {"lo_c": 25, "hi_c": 22}, "21-24", [21, 24],
                                 {"lo_c": float("nan"), "hi_c": 24}, {"lo_c": True, "hi_c": 24}, {"lo_c": float("inf"), "hi_c": 24}])
def test_unusable_stored_band_falls_back_to_the_70_75_default(raw):
    r = zb.resolve_band(raw)
    assert r["source"] == "default" and r["lo_c"] == zb.DEFAULT_LO_C and r["hi_c"] == zb.DEFAULT_HI_C and r["reason"]


@pytest.mark.parametrize("raw,err", [(None, "missing"), ({}, "finite"), ({"lo_c": 21}, "finite"), ({"lo_c": float("nan"), "hi_c": 24}, "finite"),
                                     ({"lo_c": "warm", "hi_c": 24}, "finite"), ({"lo_c": 25, "hi_c": 22}, "inverted"), ("x", "must be")])
def test_save_rejects_missing_nan_non_numeric_and_inverted(raw, err):
    with pytest.raises(ValueError, match=err):
        zb.validate_band(raw)


def test_clamping_negative_out_of_range_and_the_deadband():
    near = lambda b, lo, hi: (b["lo_c"] == pytest.approx(lo) and b["hi_c"] == pytest.approx(hi))  # noqa: E731
    assert near(zb.validate_band({"lo_c": -5, "hi_c": 99}), zb.LIMIT_LO_C, zb.LIMIT_HI_C)
    assert near(zb.validate_band({"lo_c": -30, "hi_c": -10}), zb.LIMIT_LO_C, zb.LIMIT_LO_C + zb.MIN_DEADBAND_K)
    assert near(zb.validate_band({"lo_c": 30, "hi_c": 40}), zb.LIMIT_HI_C - zb.MIN_DEADBAND_K, zb.LIMIT_HI_C)
    assert near(zb.validate_band({"lo_c": "20.5", "hi_c": "24.5"}), 20.5, 24.5)
    # exactly at the deadband is kept, just under it is widened, equal handles are widened
    assert near(zb.validate_band({"lo_c": 21, "hi_c": 21 + zb.MIN_DEADBAND_K}), 21, 21 + zb.MIN_DEADBAND_K)
    assert near(zb.validate_band({"lo_c": 21, "hi_c": 21 + zb.MIN_DEADBAND_K - 0.001}), 21, 21 + zb.MIN_DEADBAND_K)
    assert near(zb.validate_band({"lo_c": 22, "hi_c": 22}), 22, 22 + zb.MIN_DEADBAND_K)
    # both range limits: lo 79 F / hi 80 F, lo 65 F / hi 66 F
    assert near(zb.validate_band({"lo_c": F2C(79), "hi_c": F2C(80)}), F2C(78), F2C(80))
    assert near(zb.validate_band({"lo_c": F2C(65), "hi_c": F2C(66)}), F2C(65), F2C(67))
    assert near(zb.validate_band({"lo_c": F2C(65), "hi_c": F2C(80)}), F2C(65), F2C(80))


def _node(script: str, payload):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    out = subprocess.run([node, "-e", script, str(ROOT / "shared" / "zone-band.js")], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_python_and_js_agree_on_validate_and_resolve():
    cases = [None, {}, {"lo_c": 22}, {"lo_c": "x", "hi_c": 24}, {"lo_c": 25, "hi_c": 22}, {"lo_c": -5, "hi_c": 99}, {"lo_c": 22, "hi_c": 22},
             {"lo_c": 21, "hi_c": 22}, {"lo_c": F2C(79), "hi_c": F2C(80)}, {"lo_c": F2C(65), "hi_c": F2C(66)}, {"lo_c": 20, "hi_c": 25}, {"lo_c": "20.5", "hi_c": "24.5"}]
    js = _node("const Z=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>console.log(JSON.stringify(JSON.parse(s).map(c=>{const r=Z.resolveBand(c);return {lo_c:r.lo_c,hi_c:r.hi_c,source:r.source}}))))", cases)
    for case, got in zip(cases, js):
        want = zb.resolve_band(case)
        assert got["source"] == want["source"], case
        assert got["lo_c"] == pytest.approx(want["lo_c"]) and got["hi_c"] == pytest.approx(want["hi_c"]), case


def test_apply_to_params_precedence():
    p = {"zone_t_lo": zb.DEFAULT_LO_C, "zone_t_hi": zb.DEFAULT_HI_C, "confirm_min": 15}
    band = {"lo_c": 20.0, "hi_c": 25.0}
    assert zb.apply_to_params(p, band) == {"zone_t_lo": 20.0, "zone_t_hi": 25.0, "confirm_min": 15}
    assert zb.apply_to_params({**p, "zone_t_lo": 19, "zone_t_hi": 27}, band, explicit={"zone_t_lo", "zone_t_hi"})["zone_t_hi"] == 27
    assert zb.apply_to_params({**p, "zone_t_hi": 26}, band, explicit={"zone_t_hi"}) == {"zone_t_lo": 20.0, "zone_t_hi": 26, "confirm_min": 15}
    assert zb.apply_to_params({**p, "zone_t_lo": 24.5}, band, explicit={"zone_t_lo"})["zone_t_hi"] == zb.DEFAULT_HI_C   # would leave < 2 F
    assert zb.apply_to_params({"comfort_low": 21, "comfort_high": 24}, band) == {"comfort_low": 20.0, "comfort_high": 25.0}
    assert zb.apply_to_params(p, None) == p and p["zone_t_lo"] == zb.DEFAULT_LO_C                                     # input never mutated


def test_occupancy_document_carries_the_band():
    from open_fdd.analytics.occupancy import OccupancySchedule

    s = OccupancySchedule.from_dict({"timezone": "America/Chicago", "zone_band": {"lo_c": 20, "hi_c": 25}})
    assert s.zone_band == {"lo_c": 20, "hi_c": 25} and s.to_dict()["zone_band"] == {"lo_c": 20, "hi_c": 25}
    assert OccupancySchedule.from_dict({"zone_band": {"lo_c": 26, "hi_c": 20}}).zone_band is None        # unusable: the default applies
    assert "zone_band" not in OccupancySchedule().to_dict()                                                # an old calendar is unchanged
    assert OccupancySchedule.from_dict({"zone_band": {"lo_c": -9, "hi_c": 99}}).zone_band == {"lo_c": zb.LIMIT_LO_C, "hi_c": zb.LIMIT_HI_C}


def _band_in_sql(sql: str, rule_pair=("zone_air_temperature < ", " OR zone_air_temperature > ")):
    m = re.search(r"zone_air_temperature < ([-0-9.e+]+) OR zone_air_temperature > ([-0-9.e+]+)", sql)
    return (float(m[1]), float(m[2])) if m else None


def test_render_rule_vav1_and_sched1_use_the_saved_band_and_explicit_tuning_wins():
    import render_rule as rr

    shipped = rr.render("VAV-1")
    assert _band_in_sql(shipped) == pytest.approx((zb.DEFAULT_LO_C, zb.DEFAULT_HI_C), abs=1e-6)
    assert rr.render("VAV-1", zone_band=None) == shipped
    assert rr.render("VAV-1", zone_band={"lo_c": 26, "hi_c": 20}) == shipped                              # unusable: ignored
    banded = rr.render("VAV-1", zone_band={"lo_c": 20, "hi_c": 25})
    assert _band_in_sql(banded) == (20.0, 25.0)
    assert _band_in_sql(rr.render("VAV-1", overrides={"zone_t_hi": 26.5}, zone_band={"lo_c": 20, "hi_c": 25})) == (20.0, 26.5)
    assert _band_in_sql(rr.render("VAV-1", overrides={"zone_t_lo": 19, "zone_t_hi": 27}, zone_band={"lo_c": 20, "hi_c": 25})) == (19.0, 27.0)
    sched = rr.render("SCHED-1", zone_band={"lo_c": 20, "hi_c": 25})
    assert "zone_air_temperature >= 20 AND zone_air_temperature <= 25" in sched and sched != rr.render("SCHED-1")
    assert "zone_air_temperature >= 19 AND zone_air_temperature <= 25" in rr.render("SCHED-1", overrides={"comfort_low": 19}, zone_band={"lo_c": 20, "hi_c": 25})


def test_render_rule_cli_and_js_hook_render_the_same_sql_for_the_same_band():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    import render_rule as rr

    script = ("const fdd=require(process.argv[1]+'/nf-app/hooks/fdd.js');const pack=require(process.argv[1]+'/nf-app/rules/pack-postgres.json');"
              "const rows=[{site_id:'S',rule_id:'OCC-CALENDAR',scope_key:'site',revision:3,parameters:{version:1,calendar:{timezone:'America/Chicago',days:{},zone_band:{lo_c:20,hi_c:25}}}}];"
              "fdd.loadRoleLimitOverrides({engine:{ruleConfigOverrides:async()=>rows},pack,log:()=>{}}).then(t=>console.log(JSON.stringify(['VAV-1','SCHED-1'].map(id=>t.forRule('S','E',id).sql))))")
    out = subprocess.run([node, "-e", script, str(ROOT)], capture_output=True, text=True, encoding="utf-8", check=True)
    js = json.loads(out.stdout)
    for rid, got in zip(["VAV-1", "SCHED-1"], js):
        assert got == rr.render(rid, zone_band={"lo_c": 20, "hi_c": 25}), f"{rid}: JS hook SQL differs from the Python renderer"


def test_pandas_runner_params_follow_the_band_under_explicit_tuning():
    from open_fdd.rules import cookbook_catalog as cb
    from open_fdd.rules.runner import _params_for_rule

    for rid, lo_k, hi_k in (("VAV-1", "zone_lo", "zone_hi"), ("SCHED-1", "comfort_low", "comfort_high")):
        rule = cb.RULES_BY_ID[rid]
        base = _params_for_rule(rule, {})
        assert base[lo_k] == pytest.approx(zb.DEFAULT_LO_C, abs=1e-5) and base[hi_k] == pytest.approx(zb.DEFAULT_HI_C, abs=1e-5)
        band = {"zone_band": {"lo_c": 20, "hi_c": 25}}
        p = _params_for_rule(rule, {"_site": band})
        assert (p[lo_k], p[hi_k]) == (20.0, 25.0), rid
        p = _params_for_rule(rule, {rid: {hi_k: 26.0}, "_site": band})
        assert (p[lo_k], p[hi_k]) == (20.0, 26.0), f"{rid}: an explicit per-rule value wins"
        p = _params_for_rule(rule, {"_site": {"zone_band": {"lo_c": 26, "hi_c": 20}}})
        assert (p[lo_k], p[hi_k]) == (base[lo_k], base[hi_k]), "an unusable band leaves the shipped default"


def test_zone_comfort_analytics_recompute_with_the_band():
    pytest.importorskip("pandas")
    duckdb = pytest.importorskip("duckdb")
    from open_fdd.analytics import point_stats as ps
    from open_fdd.analytics import sql_point_stats as sps
    import test_sql_point_stats as base

    long = base._long4()
    conn = duckdb.connect(":memory:")
    try:
        base._load(conn, "duckdb", long)
        occ = base.OCC
        default = sps.run_zone_comfort_sql(conn, "duckdb", occ)                               # no band: the 70-75 F default
        explicit = sps.run_zone_comfort_sql(conn, "duckdb", occ, lo_c=zb.DEFAULT_LO_C, hi_c=zb.DEFAULT_HI_C)
        assert [r["pct_in_band"] for r in default] == [r["pct_in_band"] for r in explicit]
        sql = sps.render_zone_comfort_sql("duckdb", occ, band={"lo_c": 20.0, "hi_c": 27.0})
        assert "value >= 20.0 AND value <= 26.666666666666668" in sql, "the saved band is clamped to 80 F and fills {lo} / {hi}"
        wide = sps.run_zone_comfort_sql(conn, "duckdb", occ, band={"lo_c": 20.0, "hi_c": 26.5})
        by = lambda rows: {r["point_key"]: r["pct_in_band"] for r in rows}  # noqa: E731
        print(f"ZONE-BAND-PROOF zone_comfort.sql default 21.1-23.9 C {by(default)} -> saved band 20-26.5 C {by(wide)}")
        assert by(wide)["v2/zt"] > by(default)["v2/zt"] + 10, "the hot zone is mostly comfortable in the wider band"
        # the SQL equals the pandas twin for the same saved band
        twin = ps.zone_comfort(long, occ, lo_c=20.0, hi_c=26.5)
        for r in twin.to_dict("records"):
            assert by(wide)[r["point_key"]] == pytest.approx(r["pct_in_band"])
        # a bad saved band is the default again, never a bad edge; one-sided explicit input is refused
        assert by(sps.run_zone_comfort_sql(conn, "duckdb", occ, band={"lo_c": 27, "hi_c": 20})) == by(default)
        assert by(sps.run_zone_comfort_sql(conn, "duckdb", occ, band={})) == by(default)
        with pytest.raises(ValueError):
            sps.render_zone_comfort_sql("duckdb", occ, lo_c=21.0)
        for r in default:
            assert not math.isnan(r["pct_in_band"])
    finally:
        conn.close()