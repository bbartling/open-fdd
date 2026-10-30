"""Legacy-equivalent analytics thresholds across imperial and SI processing."""

from __future__ import annotations

import datetime as dt
import os
import unittest

import pandas as pd

from scripts.stress.si_cutover import analytics_parity as ap
from scripts.stress.si_cutover import ci_fixtures_lib as cfl


class W4fThresholdParityTests(unittest.TestCase):
    def _dataset(self, values: dict[str, list[float]], *, per_day: int | None = None):
        n = len(next(iter(values.values())))
        if per_day:
            index = pd.DatetimeIndex(
                [
                    ts
                    for day in range((n + per_day - 1) // per_day)
                    for ts in pd.date_range(
                        pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(days=day),
                        periods=min(per_day, n - day * per_day),
                        freq="h",
                    )
                ]
            )
        else:
            index = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="h")
        ip = cfl.prepare_ip_frame(
            pd.DataFrame(values, index=index),
            building_id="threshold_fixture",
            equipment_id="equip:threshold",
            equipment_type="ahu",
        )
        ds = ap.AnalyticsDataset(
            "threshold_fixture", "threshold_fixture", "equip:threshold", "ahu", ip
        )
        metric = ap._metric()
        si = cfl.frame_to_si(ip, metric)
        units = ap.role_units_of(ip)
        if "dsp" in ip:
            # `dsp` is a declared air-pressure SQL role; source values here are
            # in inches water column, then converted once for the SI oracle.
            self.assertEqual(units["dsp"], ("air_pressure", "inWC"))
            si["dsp"] = [ap._to_si(metric, "air_pressure", v, "inWC") for v in ip["dsp"]]
            si.attrs["unit_system"] = "metric"
        return ds, ip, si, units, metric

    def _rows(self, stem: str, ds, frame, params, units, metric):
        return ap.norm_rows(
            stem,
            ap.pandas_rows(
                stem,
                frame,
                ds=ds,
                params=params,
                as_of=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
                unit_system="metric" if frame.attrs.get("unit_system") == "metric" else "imperial",
                source_role_units=units,
                metric=metric,
            ),
        )

    def test_pid_thresholds_preserve_temperature_pressure_and_percent_flags(self) -> None:
        # Sample standard deviations exceed/below each legacy 8-native-unit limit.
        values = {
            "zone-air-temp": [70.0 + (8.2 if i % 2 else -8.2) for i in range(25)],
            "dsp": [0.0 if i % 2 else 16.4 for i in range(25)],
            "fan-cmd": [50.0 + (8.2 if i % 2 else -8.2) for i in range(25)],
        }
        ds, ip, si, units, metric = self._dataset(values)
        params = {"pid_hunting_proxy": {}}
        ip_rows = self._rows("pid_hunting_proxy", ds, ip, params, units, metric)
        si_rows = self._rows("pid_hunting_proxy", ds, si, params, units, metric)
        ip_as_si = ap.rows_ip_to_si("pid_hunting_proxy", ip_rows, units, metric)
        comparisons, errors = ap.compare_rows(
            "threshold-fixture", "pid", "pid_hunting_proxy", "ip", ip_as_si, "si", si_rows
        )
        self.assertEqual(comparisons, 3)
        self.assertEqual(errors, [])
        flags = {row[1]: row[6] for row in si_rows}
        self.assertEqual(
            flags,
            {"zone_t": "HUNT_PROXY", "dsp": "HUNT_PROXY", "fan_cmd": "HUNT_PROXY"},
        )

        below = {
            "zone-air-temp": [70.0 + (7.8 if i % 2 else -7.8) for i in range(25)],
            "dsp": [0.0 if i % 2 else 15.6 for i in range(25)],
            "fan-cmd": [50.0 + (7.8 if i % 2 else -7.8) for i in range(25)],
        }
        ds, ip, si, units, metric = self._dataset(below)
        ip_rows = self._rows("pid_hunting_proxy", ds, ip, params, units, metric)
        si_rows = self._rows("pid_hunting_proxy", ds, si, params, units, metric)
        self.assertEqual([r[6] for r in ip_rows], ["OK"] * 3)
        self.assertEqual([r[6] for r in si_rows], ["OK"] * 3)

    def test_change_point_temperature_threshold_preserves_legacy_zero_f_origin(self) -> None:
        # Six points per day remain after the shared half-open window clips the last sample.
        values = [-20.0] * 7 + [-14.9] * 7  # 5.1°F rise over the 5°F legacy threshold.
        ds, ip, si, units, metric = self._dataset({"zone-air-temp": values}, per_day=7)
        params = {"mv_change_point_daily": {}}
        ip_rows = self._rows("mv_change_point_daily", ds, ip, params, units, metric)
        si_rows = self._rows("mv_change_point_daily", ds, si, params, units, metric)
        ip_as_si = ap.rows_ip_to_si("mv_change_point_daily", ip_rows, units, metric)
        comparisons, errors = ap.compare_rows(
            "threshold-fixture", "change", "mv_change_point_daily", "ip", ip_as_si, "si", si_rows
        )
        self.assertEqual(comparisons, 1)
        self.assertEqual(errors, [])
        self.assertEqual(si_rows[0][8], "CHANGE")

        values = [-20.0] * 7 + [-15.1] * 7  # 4.9°F is below the same legacy threshold.
        ds, ip, si, units, metric = self._dataset({"zone-air-temp": values}, per_day=7)
        ip_rows = self._rows("mv_change_point_daily", ds, ip, params, units, metric)
        si_rows = self._rows("mv_change_point_daily", ds, si, params, units, metric)
        self.assertEqual(ip_rows, [])
        self.assertEqual(si_rows, [])

    def test_sql_uses_converted_legacy_thresholds_for_typed_roles(self) -> None:
        pid = (ap.REPO / "sql/analytics/postgres/queries/pid_hunting_proxy.sql").read_text()
        change = (ap.REPO / "sql/analytics/postgres/queries/mv_change_point_daily.sql").read_text()
        self.assertIn("4.444444444444445", pid)
        self.assertIn("1990.72", pid)
        self.assertIn("role NOT IN ('sat', 'zone_t', 'dsp')", pid)
        self.assertIn("prev_avg - (-17.77777777777778)", change)
        self.assertIn("0.5555555555555556", change)
        self.assertIn("ELSE greatest(abs(prev_avg) * 0.25, 1.0)", change)

    @unittest.skipUnless(
        os.environ.get("OPENFDD_DATABASE_URL", "").strip(),
        "OPENFDD_DATABASE_URL required for live analytics threshold fixture",
    )
    def test_live_sql_matches_si_threshold_oracles_at_boundary_fixture(self) -> None:
        from scripts.stress.si_cutover import ci_analytics_p2 as cap2
        from scripts.stress.si_cutover import ci_timescale_sql as cts

        index = pd.DatetimeIndex(
            [
                ts
                for day in range(2)
                for ts in pd.date_range(
                    pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(days=day),
                    periods=24,
                    freq="h",
                )
            ]
            + [pd.Timestamp("2026-01-03T00:00:00Z")]
        )
        zone = [
            (-20.0 if day == 0 else -14.9) + (8.2 if i % 2 else -8.2)
            for day in range(2)
            for i in range(24)
        ] + [-14.9]
        ip = cfl.prepare_ip_frame(
            pd.DataFrame(
                {
                    "zone-air-temp": zone,
                    "dsp": [0.0 if i % 2 else 16.4 for i in range(48)] + [0.0],
                    "fan-cmd": [50.0 + (8.2 if i % 2 else -8.2) for i in range(48)] + [50.0],
                },
                index=index,
            ),
            building_id="w4f-threshold-fixture",
            equipment_id="equip:threshold",
            equipment_type="ahu",
        )
        metric = ap._metric()
        si = cfl.frame_to_si(ip, metric)
        units = ap.role_units_of(ip)
        si["dsp"] = [ap._to_si(metric, "air_pressure", v, "inWC") for v in ip["dsp"]]
        si.attrs["unit_system"] = "metric"
        ws, we = ap.window_of(si)
        conn = cts._load_parity_module().connect_with_retry(os.environ["OPENFDD_DATABASE_URL"])
        try:
            cap2._seed_si_site(
                conn,
                building_id="w4f-threshold-fixture",
                equipment_id="equip:threshold",
                equip_type="ahu",
                si_frame=si,
            )
            live: dict[str, list[tuple]] = {}
            for stem in ("pid_hunting_proxy", "mv_change_point_daily"):
                with conn.cursor() as cur:
                    live[stem] = cap2._exec_analytics_sql(
                        cur,
                        stem,
                        site_id="w4f-threshold-fixture",
                        window_start=ws,
                        window_end=we,
                        equipment_ids=["equip:threshold"],
                    )
            ds = ap.AnalyticsDataset(
                "threshold_fixture", "w4f-threshold-fixture", "equip:threshold", "ahu", ip
            )
            units = ap.role_units_of(ip)
            self.assertEqual(units["dsp"], ("air_pressure", "inWC"))
            as_of = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
            for stem in ("pid_hunting_proxy", "mv_change_point_daily"):
                expected = ap.norm_rows(
                    stem,
                    ap.pandas_rows(
                        stem,
                        si,
                        ds=ds,
                        params={stem: {}},
                        as_of=as_of,
                        unit_system="metric",
                        source_role_units=units,
                        metric=metric,
                    ),
                )
                comparisons, errors = ap.compare_rows(
                    "live-threshold-fixture",
                    stem,
                    stem,
                    "sql_si",
                    ap.norm_rows(stem, list(live[stem])),
                    "pandas_si",
                    expected,
                )
                self.assertGreater(comparisons, 0, stem)
                self.assertEqual(
                    errors,
                    [],
                    "\n".join(errors)
                    + f"\nSQL rows: {live[stem]!r}\nPandas SI rows: {expected!r}",
                )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
