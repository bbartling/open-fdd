"""Offline tests for SI cutover IP baseline capture (T1284 W0b)."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "scripts" / "stress"
SI_CUTOVER = STRESS / "si_cutover"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))


def _load_capture():
    spec = importlib.util.spec_from_file_location(
        "capture_ip_baseline",
        SI_CUTOVER / "capture_ip_baseline.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_ip_baseline"] = module
    spec.loader.exec_module(module)
    return module


capture = _load_capture()
baseline_io = importlib.import_module("si_cutover.baseline_io")
baseline_history = importlib.import_module("si_cutover.baseline_history")


class CaptureIpBaselineSelfTest(unittest.TestCase):
    def test_cli_self_test_exits_zero(self) -> None:
        self.assertEqual(capture.main(["--self-test"]), 0)

    def test_jsonl_gz_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl.gz"
            row = {"building_id": "X", "n": 1}
            with baseline_io.JsonlGzWriter(path) as writer:
                writer.write(row)
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                loaded = json.loads(fh.read().strip())
            self.assertEqual(loaded, row)

    def test_manifest_lists_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            sample = out / "sql_fdd_daily.jsonl.gz"
            with baseline_io.JsonlGzWriter(sample) as writer:
                writer.write({"building_id": "S", "rule_id": "FC1"})
            meta = {"captured_at": "2026-01-01T00:00:00Z"}
            manifest_path = baseline_io.write_manifest(out, meta=meta)
            doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "openfdd-si-ip-baseline-manifest-v1")
            self.assertEqual(len(doc["files"]), 1)
            self.assertTrue(doc["files"][0]["sha256"])


class CaptureRequirements(unittest.TestCase):
    def test_require_database_url_missing_fails(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                capture.require_database_url()
            msg = str(ctx.exception)
            self.assertIn("OPENFDD_DATABASE_URL", msg)
            self.assertIn("--database-url", msg)

    def test_require_database_url_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"OPENFDD_DATABASE_URL": "postgresql://x"}, clear=True):
            self.assertEqual(capture.require_database_url(), "postgresql://x")

    def test_resolve_capture_password_reads_jwt_env_keys(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"OPENFDD_AGENT_PASSWORD": "from-env"},
            clear=True,
        ):
            args = argparse.Namespace(password=None)
            self.assertEqual(capture.resolve_capture_password(args), "from-env")
        args_explicit = argparse.Namespace(password="cli")
        self.assertEqual(capture.resolve_capture_password(args_explicit), "cli")

    def test_main_exits_nonzero_on_pandas_pair_errors(self) -> None:
        jwt = tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False)
        sites = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        try:
            jwt.write("OPENFDD_API_BASE=http://127.0.0.1:8080\n")
            jwt.flush()
            sites.write(json.dumps([{"building_id": "SITE_A"}]))
            sites.flush()
            env = {
                "OPENFDD_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/openfdd",
            }
            summary = {
                "building_id": "SITE_A",
                "pandas_errors": ["FC1/AHU_1: boom"],
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(capture, "load_dotenv_file"):
                    with mock.patch.object(capture, "load_sites_config", return_value=[{"building_id": "SITE_A"}]):
                        with mock.patch.object(capture, "load_rule_registry", return_value=[{"rule_id": "FC1"}]):
                            with mock.patch.object(capture, "HttpClient") as client_cm:
                                http = mock.MagicMock()
                                client_cm.return_value.__enter__ = mock.Mock(return_value=http)
                                client_cm.return_value.__exit__ = mock.Mock(return_value=False)
                                with mock.patch.object(capture, "wait_until_ready"):
                                    with mock.patch.object(capture, "login", return_value={}):
                                        with mock.patch.object(capture, "health_shortsha", return_value="abc1234"):
                                            with mock.patch.object(capture, "db_connect") as db_cm:
                                                conn = mock.MagicMock()
                                                db_cm.return_value.__enter__ = mock.Mock(return_value=conn)
                                                db_cm.return_value.__exit__ = mock.Mock(return_value=False)
                                                with mock.patch.object(
                                                    capture,
                                                    "capture_site",
                                                    return_value=summary,
                                                ):
                                                    with mock.patch.object(capture, "require_pandas_oracle"):
                                                        rc = capture.main(
                                                            [
                                                                "--jwt-env",
                                                                jwt.name,
                                                                "--sites-config",
                                                                sites.name,
                                                                "--skip-pandas",
                                                            ]
                                                        )
            self.assertEqual(rc, 1)
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(capture, "load_dotenv_file"):
                    with mock.patch.object(capture, "load_sites_config", return_value=[{"building_id": "SITE_A"}]):
                        with mock.patch.object(capture, "load_rule_registry", return_value=[{"rule_id": "FC1"}]):
                            with mock.patch.object(capture, "HttpClient") as client_cm:
                                http = mock.MagicMock()
                                client_cm.return_value.__enter__ = mock.Mock(return_value=http)
                                client_cm.return_value.__exit__ = mock.Mock(return_value=False)
                                with mock.patch.object(capture, "wait_until_ready"):
                                    with mock.patch.object(capture, "login", return_value={}):
                                        with mock.patch.object(capture, "health_shortsha", return_value="abc1234"):
                                            with mock.patch.object(capture, "db_connect") as db_cm:
                                                conn = mock.MagicMock()
                                                db_cm.return_value.__enter__ = mock.Mock(return_value=conn)
                                                db_cm.return_value.__exit__ = mock.Mock(return_value=False)
                                                with mock.patch.object(
                                                    capture,
                                                    "capture_site",
                                                    return_value=summary,
                                                ):
                                                    with mock.patch.object(capture, "require_pandas_oracle"):
                                                        rc_ok = capture.main(
                                                            [
                                                                "--jwt-env",
                                                                jwt.name,
                                                                "--sites-config",
                                                                sites.name,
                                                                "--skip-pandas",
                                                                "--allow-errors",
                                                            ]
                                                        )
            self.assertEqual(rc_ok, 0)
        finally:
            os.unlink(jwt.name)
            os.unlink(sites.name)


class BaselineHistoryPaging(unittest.TestCase):
    def test_load_samples_pages_beyond_5000(self) -> None:
        page_size = baseline_history.PAGE_SIZE
        total = page_size + 1500
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        all_rows = [(start + timedelta(minutes=i), float(i)) for i in range(total)]

        conn = mock.MagicMock()
        state = {"loads": 0}

        def fetchone():
            return (total,)

        def fetchall():
            if state["loads"] == 0:
                state["loads"] = 1
                return all_rows[:page_size]
            if state["loads"] == 1:
                state["loads"] = 2
                return all_rows[page_size:]
            return []

        def make_cursor():
            cur = mock.MagicMock()
            cur.fetchone.side_effect = fetchone
            cur.fetchall.side_effect = fetchall
            return cur

        conn.cursor.return_value.__enter__ = mock.Mock(side_effect=make_cursor)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)

        loaded = baseline_history.load_samples_in_window(
            conn,
            site_id="B1",
            openfdd_key="AHU_1.fan_status",
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-06-08T00:00:00Z",
            page_size=page_size,
        )
        self.assertEqual(len(loaded), total)


class CaptureFixtureStack(unittest.TestCase):
    """Mocked stack run: output shapes and telemetry counts unchanged."""

    def test_capture_site_telemetry_unchanged(self) -> None:
        building_id = "SYNTH_CI_BASELINE"
        run_resp = {
            "ok": True,
            "run_id": "run-ci-1",
            "window_start": "2026-06-01T00:00:00Z",
            "window_end": "2026-06-02T00:00:00Z",
        }
        counts = {"sample": 12, "point_map": 4, "authorized_series": 4}

        class FakeHttp:
            def post_json(self, path, headers=None, json_body=None):
                return run_resp

            def get_json(self, path, headers=None, params=None):
                if path == "/api/csv/import/package/mapping":
                    return {
                        "session_config": {"unit_system": "imperial"},
                        "columns": [
                            {
                                "openfdd_key": "AHU_1.fan_status",
                                "role": "fan-status",
                                "unit": "1",
                            }
                        ],
                    }
                if path == "/api/fdd/equipment":
                    return {"equipment": [{"equipment_id": "AHU_1", "equip_type": "ahu"}]}
                return {}

        fake_conn = mock.MagicMock()
        fake_cursor = mock.MagicMock()
        fake_conn.cursor.return_value.__enter__ = mock.Mock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        count_values = [n for n in counts.values()] * 2
        fake_cursor.fetchone.side_effect = [(n,) for n in count_values]
        fake_cursor.fetchall.side_effect = [
            [],
            [("AHU_1.fan_status", "1")],
        ]

        sql_row = {
            "building_id": building_id,
            "rule_id": "FC1",
            "equipment_id": "AHU_1",
            "utc_day": "2026-06-01",
            "fault_seconds": 180.0,
            "covered_seconds": 3600.0,
            "status": "FAULT",
        }

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with mock.patch.object(capture, "fetch_sql_daily_rows", return_value=[sql_row]):
                with mock.patch.object(capture, "fetch_run_status_rows", return_value={}):
                    with mock.patch.object(capture, "analytics_rows_for_site", return_value=[]):
                        with mock.patch.object(
                            capture,
                            "post_fdd_run_with_busy_retry",
                            return_value=(run_resp, {"http_attempts": [{"attempt": 1, "http_status": 200}]}),
                        ):
                            summary = capture.capture_site(
                                FakeHttp(),
                                {},
                                fake_conn,
                                site={"building_id": building_id},
                                out_dir=out_dir,
                                rules=[{"rule_id": "FC1", "pandas_function": "fc1"}],
                                skip_pandas=True,
                                pandas_max_rules=None,
                            )
            self.assertEqual(summary["building_id"], building_id)
            site_dir = out_dir / building_id
            for name in (
                "sql_fdd_daily.jsonl.gz",
                "analytics_rows.jsonl.gz",
                "pandas_fdd_daily.jsonl.gz",
                "unit_inventory.jsonl.gz",
                "sample_counts.jsonl.gz",
                "persisted_runs.jsonl.gz",
            ):
                self.assertTrue((site_dir / name).is_file(), name)
            with gzip.open(site_dir / "persisted_runs.jsonl.gz", "rt", encoding="utf-8") as fh:
                persisted = json.loads(fh.read().strip())
            self.assertEqual(persisted["run_id"], "run-ci-1")


class DailyFaultSecondsTest(unittest.TestCase):
    def test_forward_hold_at_utc_midnight_boundary(self) -> None:
        import pandas as pd

        idx = pd.DatetimeIndex(
            ["2026-06-01T23:55:00+00:00", "2026-06-02T00:00:00+00:00"],
            tz="UTC",
        )
        confirmed = pd.Series([True, False], index=idx)
        fault_days, covered_days = capture.daily_fault_and_covered_seconds(
            confirmed, idx, poll_seconds=300.0
        )
        self.assertAlmostEqual(fault_days["2026-06-01"], 300.0)
        self.assertAlmostEqual(covered_days["2026-06-01"], 300.0)
        self.assertEqual(fault_days.get("2026-06-02", 0.0), 0.0)


class EquipmentFrameMetadataTest(unittest.TestCase):
    def test_equipment_frame_from_db_stamps_equipment_type(self) -> None:
        import pandas as pd

        idx = pd.date_range("2026-06-01", periods=3, freq="5min", tz="UTC")
        with mock.patch.object(
            capture,
            "post_sparql",
            return_value=[
                {
                    "column": "dsp",
                    "fddSelection": "duct-static-pressure",
                    "openfdd_key": "AHU_1.dsp",
                },
            ],
        ):
            with mock.patch.object(
                capture,
                "load_samples_in_window",
                return_value=[(ts, 1.0) for ts in idx],
            ):
                frame, skips = capture.equipment_frame_from_db(
                    mock.MagicMock(),
                    mock.MagicMock(),
                    {},
                    building_id="SITE_X",
                    equipment_id="AHU_1",
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-01T01:00:00Z",
                    equipment_type="ahu",
                )
        self.assertEqual(frame.attrs.get("equipment_type"), "ahu")
        self.assertEqual(frame.attrs.get("equipType"), "ahu")
        self.assertEqual(skips.get("skipped_other_equipment", 0), 0)


class CollectPandasFddRowsIntegration(unittest.TestCase):
    """Exercise collect_pandas_fdd_rows end-to-end (oracle import + run_rule)."""

    def test_collect_pandas_fdd_rows_imperial_fixture(self) -> None:
        import pandas as pd

        fc1_rules = [r for r in capture.load_rule_registry() if r.get("rule_id") == "FC1"]
        self.assertEqual(len(fc1_rules), 1)

        building_id = "SYNTH_PANDAS_CAPTURE"
        window_start = "2026-06-01T00:00:00Z"
        window_end = "2026-06-01T06:00:00Z"
        idx = pd.date_range("2026-06-01", periods=24, freq="5min", tz="UTC")

        sparql_points = [
            {
                "column": "dsp",
                "fddSelection": "duct-static-pressure",
                "openfdd_key": "AHU_1.dsp",
            },
            {
                "column": "dsps",
                "fddSelection": "duct-static-pressure-sp",
                "openfdd_key": "AHU_1.dsps",
            },
            {"column": "fc", "fddSelection": "fan-cmd", "openfdd_key": "AHU_1.fc"},
            {"column": "fs", "fddSelection": "fan-status", "openfdd_key": "AHU_1.fs"},
        ]

        def fake_load_samples(_conn, *, openfdd_key, **_kwargs):
            if openfdd_key.endswith(".dsps"):
                val = 1.5
            else:
                val = 1.0 if "fan" in openfdd_key else 1.25
            return [(ts, val) for ts in idx]

        http = mock.MagicMock()
        http.get_json.return_value = {
            "equipment": [{"equipment_id": "AHU_1", "equip_type": "ahu"}],
        }
        conn = mock.MagicMock()

        with mock.patch.object(capture, "post_sparql", return_value=sparql_points):
            with mock.patch.object(
                capture, "load_samples_in_window", side_effect=fake_load_samples
            ):
                rows, coverage, errors, _skips = capture.collect_pandas_fdd_rows(
                    http,
                    {},
                    conn,
                    building_id=building_id,
                    rules=fc1_rules,
                    window_start=window_start,
                    window_end=window_end,
                    pandas_max_rules=None,
                )

        self.assertEqual(errors, [])
        self.assertGreater(coverage.get("computed", 0), 0)
        computed = [r for r in rows if r.get("pair_status") == "computed"]
        self.assertTrue(computed, rows)
        self.assertTrue(
            any(r.get("utc_day") == "2026-06-01" for r in computed),
            computed,
        )


class EquipmentFrameBuilderTest(unittest.TestCase):
    """Frame builder skips overlay noise and maps role ids to Haystack columns."""

    def _frame_from_points(
        self,
        equipment_id: str,
        points: list[dict],
        *,
        load_keys: set[str] | None = None,
    ):
        import pandas as pd

        idx = pd.date_range("2026-06-01", periods=2, freq="5min", tz="UTC")
        keys = load_keys or {capture.resolve_openfdd_key(equipment_id, str(p.get("column") or ""), p.get("openfdd_key")) for p in points if p.get("column")}

        def fake_load(_conn, *, openfdd_key, **_kwargs):
            if openfdd_key not in keys:
                return []
            return [(ts, 1.0) for ts in idx]

        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(capture, "load_samples_in_window", side_effect=fake_load):
                return capture.equipment_frame_from_db(
                    mock.MagicMock(),
                    mock.MagicMock(),
                    {},
                    building_id="SITE_GEN",
                    equipment_id=equipment_id,
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-01T01:00:00Z",
                    equipment_type="ahu",
                )

    def test_skips_overlay_other_equipment_and_unbound_rows(self) -> None:
        points = [
            {"equipmentId": "RTU_B", "column": "oa_t", "fddSelection": "oa_t"},
            {"equipmentId": "RTU_A", "column": "", "fddSelection": "fan_cmd"},
            {"equipmentId": "RTU_A", "column": "fc", "fddSelection": "fan_cmd", "openfdd_key": "RTU_A.fc"},
        ]
        frame, skips = self._frame_from_points("RTU_A", points)
        self.assertEqual(skips["skipped_other_equipment"], 1)
        self.assertEqual(skips["skipped_unbound_no_column"], 1)
        self.assertIn("fan-cmd", frame.columns)

    def test_prefixed_column_does_not_double_equipment_id(self) -> None:
        points = [
            {
                "equipmentId": "RTU_A",
                "column": "RTU_A.fc",
                "fddSelection": "fan_cmd",
            },
        ]
        seen: list[str] = []

        def fake_load(_conn, *, openfdd_key, **_kwargs):
            seen.append(openfdd_key)
            import pandas as pd

            idx = pd.date_range("2026-06-01", periods=2, freq="5min", tz="UTC")
            return [(ts, 1.0) for ts in idx]

        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(capture, "load_samples_in_window", side_effect=fake_load):
                frame, _skips = capture.equipment_frame_from_db(
                    mock.MagicMock(),
                    mock.MagicMock(),
                    {},
                    building_id="SITE_GEN",
                    equipment_id="RTU_A",
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-01T01:00:00Z",
                )
        self.assertEqual(seen, ["RTU_A.fc"])
        self.assertIn("fan-cmd", frame.columns)

    def test_unmapped_role_raises_for_pair_status(self) -> None:
        points = [
            {
                "equipmentId": "RTU_A",
                "column": "mystery",
                "fddSelection": "not_in_golden_xyz",
            },
        ]
        with self.assertRaises(capture.UnmappedRoleError) as ctx:
            self._frame_from_points(
                "RTU_A",
                points,
                load_keys={capture.resolve_openfdd_key("RTU_A", "mystery", None)},
            )
        self.assertEqual(ctx.exception.skip_counts["skipped_unmapped_role"], 1)

    def test_fc1_computes_on_role_id_columns(self) -> None:
        fc1_rules = [r for r in capture.load_rule_registry() if r.get("rule_id") == "FC1"]
        self.assertEqual(len(fc1_rules), 1)
        idx = __import__("pandas").date_range("2026-06-01", periods=24, freq="5min", tz="UTC")
        points = [
            {"equipmentId": "RTU_A", "column": "dsp", "fddSelection": "duct_static"},
            {"equipmentId": "RTU_A", "column": "dsps", "fddSelection": "duct_static_sp"},
            {"equipmentId": "RTU_A", "column": "fc", "fddSelection": "fan_cmd"},
            {"equipmentId": "RTU_A", "column": "fs", "fddSelection": "fan_status"},
        ]

        def fake_load(_conn, *, openfdd_key, **_kwargs):
            val = 1.5 if openfdd_key.endswith(".dsps") else 1.0
            return [(ts, val) for ts in idx]

        http = mock.MagicMock()
        http.get_json.return_value = {
            "equipment": [{"equipment_id": "RTU_A", "equip_type": "ahu"}],
        }
        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(capture, "load_samples_in_window", side_effect=fake_load):
                rows, coverage, errors, skips = capture.collect_pandas_fdd_rows(
                    http,
                    {},
                    mock.MagicMock(),
                    building_id="SITE_GEN",
                    rules=fc1_rules,
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-01T06:00:00Z",
                    pandas_max_rules=None,
                )
        self.assertEqual(errors, [])
        self.assertGreater(coverage.get("computed", 0), 0)
        computed = [r for r in rows if r.get("pair_status") == "computed"]
        self.assertTrue(computed)


class FddRunBusyRetryTest(unittest.TestCase):
    def test_post_fdd_run_retries_409_then_succeeds(self) -> None:
        http = mock.MagicMock()
        ok_body = json.dumps({"ok": True, "run_id": "r1"}).encode("utf-8")
        http.request.side_effect = [
            (409, {}, b"busy"),
            (200, {}, ok_body),
        ]
        body, meta = capture.post_fdd_run_with_busy_retry(
            http,
            {},
            {"building_id": "B"},
            request_timeout_s=30.0,
        )
        self.assertTrue(body.get("ok"))
        self.assertEqual(len(meta["http_attempts"]), 2)
        self.assertEqual(meta["http_attempts"][0]["http_status"], 409)
        self.assertEqual(meta["http_attempts"][1]["http_status"], 200)


if __name__ == "__main__":
    unittest.main()
