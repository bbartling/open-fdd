"""SV-RANGE scale geometry — before/after counterexamples for runner C/D (#1408, PR #1481).

Documents why bound-literal × scale is wrong for absolute SI temperatures while
pandas ``_sweep_range`` uses midpoint ± (half-width × scale). Delta/rate units
stay scale-only elsewhere (``metric_units.json``); range limits are not deltas.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from open_fdd.rules.cookbook_catalog import _sweep_range
from open_fdd.rules.sensor_sweep_catalog import limits_for_haystack_role_si

REPO = Path(__file__).resolve().parents[2]
SV_RANGE_SQL = REPO / "sql" / "fdd" / "postgres" / "rules" / "sv_range.sql"


def _pandas_limits(role: str, scale: float) -> tuple[float, float]:
    lim = limits_for_haystack_role_si(role)
    assert lim is not None
    base_lo, base_hi = float(lim["lo"]), float(lim["hi"])
    mid = (base_lo + base_hi) / 2.0
    half = (base_hi - base_lo) / 2.0 * max(scale, 1e-6)
    return mid - half, mid + half


def _legacy_bound_literal_times_scale(role: str, scale: float) -> tuple[float, float]:
    """Pre-#1481 postgres pattern: each SI catalog endpoint multiplied by scale."""
    lim = limits_for_haystack_role_si(role)
    assert lim is not None
    return float(lim["lo"]) * scale, float(lim["hi"]) * scale


def _parse_postgres_oa_mid_half(sql_text: str) -> tuple[float, float, float]:
    match = re.search(
        r"oa_t < \(([-0-9.]+) - ([0-9.]+) \* \{\{RANGE_SCALE_TEMPERATURE\}\}\)"
        r" OR oa_t > \(([-0-9.]+) \+ ([0-9.]+) \* \{\{RANGE_SCALE_TEMPERATURE\}\}\)",
        sql_text,
    )
    assert match is not None, "expected midpoint half-width oa_t predicate in shipped SQL"
    mid_lo = float(match.group(1))
    half = float(match.group(2))
    mid_hi = float(match.group(3))
    assert abs(mid_lo - mid_hi) < 1e-6
    return mid_lo, half, mid_hi


class SvRangeScaleGeometryTests(unittest.TestCase):
    def test_scale_one_unchanged_vs_legacy_multiply(self) -> None:
        scale = 1.0
        role = "outside-air-temp"
        pd_lo, pd_hi = _pandas_limits(role, scale)
        leg_lo, leg_hi = _legacy_bound_literal_times_scale(role, scale)
        self.assertAlmostEqual(pd_lo, leg_lo, places=4)
        self.assertAlmostEqual(pd_hi, leg_hi, places=4)

    def test_nondefault_scale_differs_from_legacy_multiply(self) -> None:
        """Counterexample: literal×scale is not midpoint geometry at scale≠1."""
        scale = 1.5
        role = "outside-air-temp"
        pd_lo, pd_hi = _pandas_limits(role, scale)
        leg_lo, leg_hi = _legacy_bound_literal_times_scale(role, scale)
        self.assertNotAlmostEqual(pd_lo, leg_lo, places=2)
        self.assertNotAlmostEqual(pd_hi, leg_hi, places=2)

    def test_shipped_sql_oa_t_matches_pandas_midpoint_half(self) -> None:
        sql_text = SV_RANGE_SQL.read_text(encoding="utf-8")
        mid, half_coeff, _mid2 = _parse_postgres_oa_mid_half(sql_text)
        scale = 1.25
        sql_lo = mid - half_coeff * scale
        sql_hi = mid + half_coeff * scale
        pd_lo, pd_hi = _pandas_limits("outside-air-temp", scale)
        self.assertAlmostEqual(sql_lo, pd_lo, places=3)
        self.assertAlmostEqual(sql_hi, pd_hi, places=3)

    def test_sweep_range_respects_scaled_limits(self) -> None:
        import pandas as pd

        scale = 1.5
        _lo, hi = _pandas_limits("outside-air-temp", scale)
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        inside = pd.DataFrame({"outside-air-temp": [hi - 0.01, hi - 0.02]}, index=idx)
        inside.attrs["units_map"] = {"outside-air-temp": "°C"}
        outside = pd.DataFrame({"outside-air-temp": [hi + 0.5, hi + 0.6]}, index=idx)
        outside.attrs["units_map"] = {"outside-air-temp": "°C"}
        params = {"range_scale_temperature": scale}
        self.assertFalse(_sweep_range(inside, params, 300.0).any())
        self.assertTrue(_sweep_range(outside, params, 300.0).any())


if __name__ == "__main__":
    unittest.main()
