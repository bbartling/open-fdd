"""Offline tests for SI cutover IP baseline capture (T1284 W0b)."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib
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
IP_ORACLE_ROOT = Path(os.environ.get("OPENFDD_IP_ORACLE_ROOT", "/tmp/open-fdd-wt-407-ipbase"))
IP_ORACLE_COMMIT = "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0"


def ensure_ip_oracle_worktree() -> Path:
    """Detached worktree at the frozen 4.0.6 / open-fdd 4.4.9 IP oracle (CI-safe)."""
    root = IP_ORACLE_ROOT
    if (root / "pyproject.toml").is_file() and (root / "sql" / "fdd" / "registry.yaml").is_file():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists() and not (root / ".git").exists():
        raise RuntimeError(f"IP oracle path exists but is not a git worktree: {root}")
    if not root.exists():
        proc = subprocess.run(
            ["git", "worktree", "add", "--detach", str(root), IP_ORACLE_COMMIT],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            fetch = subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", IP_ORACLE_COMMIT],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            if fetch.returncode != 0:
                raise RuntimeError(
                    f"git fetch origin {IP_ORACLE_COMMIT} failed: {fetch.stderr or fetch.stdout}"
                )
            proc = subprocess.run(
                ["git", "worktree", "add", "--detach", str(root), IP_ORACLE_COMMIT],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
        if proc.returncode != 0:
            raise RuntimeError(
                f"git worktree add {root} @ {IP_ORACLE_COMMIT} failed: {proc.stderr or proc.stdout}"
            )
    return root


def purge_ip_oracle_import(root: Path | None = None) -> None:
    """Drop pinned 4.4.9 ``open_fdd`` imports so later SI qualification tests stay isolated."""
    root_s = os.path.normpath(str(root or IP_ORACLE_ROOT))
    for name in list(sys.modules):
        if name == "open_fdd" or name.startswith("open_fdd."):
            del sys.modules[name]
    sys.path[:] = [p for p in sys.path if os.path.normpath(p) != root_s]
    importlib.invalidate_caches()


MOCK_ORACLE = {
    "source_root": str(IP_ORACLE_ROOT),
    "version": "4.4.9",
    "import_path": str(IP_ORACLE_ROOT / "open_fdd" / "__init__.py"),
    "git_head": "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0",
    "registry_sha256": "b0397a06d834109a77e85599c81e7c81cbacfab7d38372503c943c1f26e1fcbf",
    "python_tree_sha256": "mock",
    "rule_count": 77,
    "rules": [{"rule_id": "FC1"}],
    "pandas_implemented_rule_ids": ["FC1"],
    "no_pandas_function_rule_ids": [],
}


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
    def test_template_binding_normalization_preserves_nested_history(self) -> None:
        from helpers import _normalize_sparql_rows

        row = _normalize_sparql_rows(
            {
                "equipment": [
                    {
                        "equipment_id": "AHU_1",
                        "points": [
                            {
                                "point_id": "portal-17",
                                "column": "dsp",
                                "canonical_role": "duct-static-pressure",
                                "openfdd_key": "AHU_1.dsp",
                                "history": {"openfdd_key": "AHU_1.dsp", "samples": 8},
                            }
                        ],
                    }
                ]
            }
        )[0]
        self.assertEqual(row["pointId"], "portal-17")
        self.assertEqual(row["canonicalRole"], "duct-static-pressure")
        self.assertEqual(row["openfdd_key"], "AHU_1.dsp")
        self.assertEqual(row["history"]["samples"], 8)

    def test_health_shortsha_reads_version_endpoint(self) -> None:
        http = mock.MagicMock()
        http.get_json.return_value = {"version": "4.0.7+35c17ac"}
        self.assertEqual(capture.health_shortsha(http, {}), "35c17ac")
        http.get_json.assert_called_once_with("/api/version", headers={})

    def test_analytics_error_rows_are_qualification_errors(self) -> None:
        errors = capture.analytics_error_messages(
            [
                {"endpoint": "/api/analytics/runtime", "row": {"ok": False, "error": "timeout"}},
                {"endpoint": "/api/analytics/ahu-health", "row": {"ok": False}},
                {"endpoint": "/api/analytics/ahu-health", "row": {"ok": True}},
            ]
        )
        self.assertEqual(
            errors,
            ["/api/analytics/runtime: timeout", "/api/analytics/ahu-health: ok=false"],
        )

    def test_oracle_source_root_is_required_before_dotenv_or_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jwt = Path(tmp) / "auth.env"
            sites = Path(tmp) / "sites.json"
            jwt.write_text("OPENFDD_API_BASE=http://127.0.0.1:8080\n", encoding="utf-8")
            sites.write_text('[{"building_id":"SITE_A"}]', encoding="utf-8")
            with mock.patch.object(capture, "load_dotenv_file") as load_env:
                with self.assertRaises(SystemExit) as ctx:
                    capture.main(["--jwt-env", str(jwt), "--sites-config", str(sites)])
            self.assertEqual(ctx.exception.code, 2)
            load_env.assert_not_called()
            with mock.patch.object(capture, "load_dotenv_file") as load_env_skip:
                with self.assertRaises(SystemExit) as ctx_skip:
                    capture.main(
                        [
                            "--jwt-env",
                            str(jwt),
                            "--sites-config",
                            str(sites),
                            "--skip-pandas",
                        ]
                    )
            self.assertEqual(ctx_skip.exception.code, 2)
            load_env_skip.assert_not_called()

    def test_disqualifying_manifest_flags_skip_pandas_and_allow_errors(self) -> None:
        meta = {
            "skip_pandas": False,
            "allow_errors": False,
            "ip_oracle": {"version": "4.4.9"},
        }
        self.assertEqual(capture.baseline_capture_disqualifiers(meta), [])
        meta_skip = dict(meta, skip_pandas=True)
        self.assertIn("skip_pandas", capture.baseline_capture_disqualifiers(meta_skip))
        meta_allow = dict(meta, allow_errors=True)
        self.assertIn("allow_errors", capture.baseline_capture_disqualifiers(meta_allow))
        meta_missing = dict(meta, ip_oracle=None)
        self.assertIn("missing_ip_oracle", capture.baseline_capture_disqualifiers(meta_missing))

    def test_oracle_source_validation_rejects_non_449_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "open_fdd").mkdir()
            (root / "sql" / "fdd").mkdir(parents=True)
            (root / "pyproject.toml").write_text('version = "5.0.0"\n', encoding="utf-8")
            (root / "sql" / "fdd" / "registry.yaml").write_text("rules: []\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                capture.load_ip_oracle(root)
            self.assertIn("4.4.9", str(ctx.exception))

    def test_oracle_source_validation_rejects_si_checkout_with_ip_version(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            capture.load_ip_oracle(REPO)
        self.assertIn("4.4.9", str(ctx.exception))

    def test_pinned_oracle_provenance_matches_frozen_registry(self) -> None:
        oracle_root = ensure_ip_oracle_worktree()
        try:
            oracle = capture.load_ip_oracle(oracle_root)
            self.assertEqual(oracle["version"], "4.4.9")
            self.assertEqual(oracle["git_head"], "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0")
            self.assertEqual(
                oracle["registry_sha256"],
                "b0397a06d834109a77e85599c81e7c81cbacfab7d38372503c943c1f26e1fcbf",
            )
            capture.require_oracle_runtime(oracle)
            self.assertEqual(len(oracle["pandas_implemented_rule_ids"]), 70)
            self.assertGreater(len(oracle["no_pandas_function_rule_ids"]), 0)
        finally:
            purge_ip_oracle_import(oracle_root)

    def test_zero_unit_inventory_with_point_map_rows_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "every point_map key"):
            capture.require_unit_inventory(1, [])
        capture.require_unit_inventory(0, [])

    def test_unit_inventory_incomplete_key_set_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "every point_map key"):
            capture.require_unit_inventory(
                2,
                [{"openfdd_key": "EQ.a"}],
            )

    def test_unit_inventory_reads_exact_point_map_rows(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchall.side_effect = [
            [("AHU_1.fan_status", ["degF", "K"], 8, None, None)],
            [("AHU_1", "fan-status", "AHU_1.fan_status", "degC", "degF")],
        ]
        http = mock.MagicMock()
        http.get_json.return_value = {
            "ok": True,
            "equipment": [{"equipment_id": "AHU_1", "columns": [{"column": "fan_status"}]}],
            "session_config": {"unit_system": "imperial"},
        }
        with mock.patch.object(capture, "post_sparql", return_value=[]):
            rows, unresolved = capture.unit_inventory_rows(http, {}, conn, building_id="SITE_X")
        self.assertEqual(unresolved, 0)
        self.assertEqual(rows[0]["openfdd_key"], "AHU_1.fan_status")
        self.assertEqual(rows[0]["sample_unit"], "")
        self.assertEqual(rows[0]["sample_unit_values"], ["K", "degF"])
        self.assertEqual(rows[0]["point_map_unit"], "degC")
        self.assertEqual(rows[0]["w2c_source_unit"], "degC")
        self.assertEqual(rows[0]["declared_source_unit"], "degF")
        self.assertTrue(rows[0]["storage_source_unit_conflict"])
        self.assertTrue(rows[0]["ambiguous_sample_units"])
        self.assertIn("to_jsonb(point_map)->>'source_unit'", cur.execute.call_args_list[1].args[0])

    def test_explicit_history_key_conflict_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            capture._explicit_openfdd_key(
                {"openfdd_key": "EQ.a", "history": {"openfdd_key": "EQ.b"}}
            )

    def test_typed_point_resolves_only_exact_identity(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchall.return_value = [("AHU_1.dsp",)]
        key = capture.resolve_bound_openfdd_key(
            conn,
            site_id="SITE_X",
            equipment_id="AHU_1",
            point={"pointId": "portal-17"},
        )
        self.assertEqual(key, "AHU_1.dsp")
        self.assertEqual(
            cur.execute.call_args_list[0].args[1],
            ("SITE_X", "AHU_1", "portal-17", "portal-17"),
        )

    def test_exact_equipment_column_key_encoding_resolves_key(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchall.side_effect = [[], [("AHU_1.dsp",)]]
        self.assertEqual(
            capture.resolve_bound_openfdd_key(
                conn,
                site_id="SITE_X",
                equipment_id="AHU_1",
                point={"pointId": "unmapped-id", "column": "dsp"},
            ),
            "AHU_1.dsp",
        )
        self.assertEqual(
            cur.execute.call_args.args[1],
            ("SITE_X", "AHU_1", ["AHU_1.dsp", "AHU_1.unmapped-id"]),
        )

    def test_ambiguous_exact_equipment_role_fails_closed(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchall.side_effect = [[], [("AHU_1.dsp",), ("AHU_1.static",)]]
        with self.assertRaisesRegex(ValueError, "multiple point_map keys"):
            capture.resolve_bound_openfdd_key(
                conn,
                site_id="SITE_X",
                equipment_id="AHU_1",
                point={"pointId": "unmapped-id", "column": "dsp"},
            )

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

    def test_main_exits_nonzero_on_capture_errors(self) -> None:
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
                "analytics_errors": ["/api/analytics/runtime: timeout"],
            }
            oracle_args = [
                "--oracle-source-root",
                str(IP_ORACLE_ROOT),
            ]

            def run_main(extra: list[str], out_name: str) -> tuple[int, dict]:
                with mock.patch.dict(os.environ, env, clear=False):
                    with mock.patch.object(capture, "load_ip_oracle", return_value=dict(MOCK_ORACLE)):
                        with mock.patch.object(capture, "require_oracle_runtime"):
                            with mock.patch.object(capture, "load_dotenv_file"):
                                with mock.patch.object(
                                    capture,
                                    "load_sites_config",
                                    return_value=[{"building_id": "SITE_A"}],
                                ):
                                    with mock.patch.object(capture, "HttpClient") as client_cm:
                                        http = mock.MagicMock()
                                        client_cm.return_value.__enter__ = mock.Mock(return_value=http)
                                        client_cm.return_value.__exit__ = mock.Mock(return_value=False)
                                        with mock.patch.object(capture, "wait_until_ready"):
                                            with mock.patch.object(capture, "login", return_value={}):
                                                with mock.patch.object(
                                                    capture,
                                                    "health_shortsha",
                                                    return_value="abc1234",
                                                ):
                                                    with mock.patch.object(capture, "db_connect") as db_cm:
                                                        conn = mock.MagicMock()
                                                        db_cm.return_value.__enter__ = mock.Mock(
                                                            return_value=conn
                                                        )
                                                        db_cm.return_value.__exit__ = mock.Mock(
                                                            return_value=False
                                                        )
                                                        with mock.patch.object(
                                                            capture,
                                                            "capture_site",
                                                            return_value=summary,
                                                        ):
                                                            out_dir = Path(jwt.name).parent / out_name
                                                            rc = capture.main(
                                                                [
                                                                    "--jwt-env",
                                                                    jwt.name,
                                                                    "--sites-config",
                                                                    sites.name,
                                                                    "--output-dir",
                                                                    str(out_dir),
                                                                    *oracle_args,
                                                                    *extra,
                                                                ]
                                                            )
                                                            manifest_doc = json.loads(
                                                                (
                                                                    out_dir / "manifest.sha256.json"
                                                                ).read_text(encoding="utf-8")
                                                            )
                                                            return rc, manifest_doc["meta"]

            rc, manifest_fail = run_main(["--skip-pandas"], "out-first")
            self.assertEqual(rc, 1)
            self.assertFalse(manifest_fail["qualifying"])
            self.assertIn("skip_pandas", manifest_fail["disqualifying_reasons"])

            rc_ok, manifest_ok = run_main(
                ["--skip-pandas", "--allow-errors"],
                "out-second",
            )
            self.assertEqual(rc_ok, 0)
            self.assertFalse(manifest_ok["qualifying"])
            self.assertIn("allow_errors", manifest_ok["disqualifying_reasons"])
            self.assertIn("skip_pandas", manifest_ok["disqualifying_reasons"])
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
        counts = {"sample": 12, "point_map": 1, "authorized_series": 1}
        run_requests: list[dict] = []
        receipt_site_dir: Path | None = None

        def fake_run(_http, _headers, run_body, **_kwargs):
            if len(run_requests) == 1:
                assert receipt_site_dir is not None
                prior_receipt = next(receipt_site_dir.rglob("batch-0000.json"))
                self.assertEqual(
                    json.loads(prior_receipt.read_text(encoding="utf-8"))["run_id"],
                    "run-ci-1",
                )
            run_requests.append(dict(run_body))
            return (
                {
                    "ok": True,
                    "run_id": f"run-ci-{len(run_requests)}",
                    "window": {
                        "start": "2026-06-01T00:05:00+00:00",
                        "end": "2026-06-02T00:00:00Z",
                    },
                },
                {"http_attempts": [{"attempt": 1, "http_status": 200}]},
            )

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
        telemetry_sample_bounds: list[str] = []

        def record_query(sql, params=None):
            if "ts < %s" in sql and params:
                telemetry_sample_bounds.append(params[1])

        fake_cursor.execute.side_effect = record_query
        fake_conn.cursor.return_value.__enter__ = mock.Mock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        count_values = [n for n in counts.values()] * 2
        fake_cursor.fetchone.side_effect = [(n,) for n in count_values]
        fake_cursor.fetchall.side_effect = [
            [("AHU_1.fan_status", ["1"], 8, None, None)],
            [("AHU_1", "fan-status", "AHU_1.fan_status", "1", "1")],
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
            receipt_site_dir = out_dir / building_id / "run_receipts"
            with mock.patch.object(capture, "fetch_sql_daily_rows", return_value=[sql_row]):
                with mock.patch.object(capture, "fetch_run_status_rows", return_value={}):
                    with mock.patch.object(
                        capture,
                        "validate_batch_persisted_scope",
                        return_value=(
                            capture.datetime.fromisoformat("2026-06-01T00:05:00+00:00"),
                            capture.datetime.fromisoformat("2026-06-01T00:05:00+00:00"),
                            capture.datetime.fromisoformat("2026-06-02T00:00:00+00:00"),
                            capture.datetime.fromisoformat("2026-06-02T00:00:00+00:00"),
                        ),
                    ):
                        with mock.patch.object(
                            capture,
                            "fdd_run_created_at_marker",
                            return_value=capture.datetime.fromisoformat(
                                "2026-06-01T00:00:00+00:00"
                            ),
                        ):
                            with mock.patch.object(capture, "assert_no_interleaved_fdd_run"):
                                with mock.patch.object(
                                    capture, "analytics_rows_for_site", return_value=[]
                                ):
                                    with mock.patch.object(capture, "post_sparql", return_value=[]):
                                        with mock.patch.object(
                                            capture,
                                            "post_fdd_run_with_busy_retry",
                                            side_effect=fake_run,
                                        ):
                                            summary = capture.capture_site(
                                                FakeHttp(),
                                                {},
                                                fake_conn,
                                                site={
                                                    "building_id": building_id,
                                                    "window_start": "2026-06-01T00:00:00Z",
                                                    "window_end": "2026-06-02T03:00:00Z",
                                                },
                                                out_dir=out_dir,
                                                rules=[
                                                    {"rule_id": "FC1"},
                                                    {"rule_id": "FC2"},
                                                ],
                                                skip_pandas=True,
                                                pandas_max_rules=None,
                                                rule_batch_size=1,
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
            self.assertEqual(persisted["run_id"], "run-ci-2")
            self.assertEqual([r["rule_ids"] for r in persisted["run_records"]], [["FC1"], ["FC2"]])
            self.assertEqual(len({(r["window_start"], r["window_end"]) for r in persisted["run_records"]}), 1)
            receipts = sorted((site_dir / "run_receipts").rglob("batch-*.json"))
            self.assertEqual(len(receipts), 2)
            self.assertEqual(json.loads(receipts[0].read_text(encoding="utf-8"))["run_id"], "run-ci-1")
            self.assertEqual([request["rule_ids"] for request in run_requests], [["FC1"], ["FC2"]])
            self.assertEqual(run_requests[0]["window_start"], "2026-06-01T00:00:00Z")
            self.assertEqual(run_requests[0]["window_end"], "2026-06-02T03:00:00Z")
            self.assertEqual(run_requests[1]["window_start"], "2026-06-01T00:05:00+00:00")
            self.assertEqual(run_requests[1]["window_end"], "2026-06-02T00:00:00Z")
            self.assertEqual(telemetry_sample_bounds, ["2026-06-02T03:00:00Z"] * 2)

    def test_rule_batches_cover_registry_once_and_reject_duplicates(self) -> None:
        rules = [{"rule_id": f"R{i}"} for i in range(5)]
        self.assertEqual(
            capture.build_rule_batches(rules, 2),
            [["R0", "R1"], ["R2", "R3"], ["R4"]],
        )
        self.assertEqual(capture.build_rule_batches(rules, 0), [[f"R{i}" for i in range(5)]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            capture.build_rule_batches([{"rule_id": "R1"}, {"rule_id": "R1"}], 1)

    def test_effective_window_reads_manifest_and_compares_instants(self) -> None:
        start, end = capture.effective_run_window(
            {"window": {"start": "2026-10-09T22:35:00+00:00", "end": "2026-10-16T12:50:00Z"}},
            requested_start="2026-10-09T22:00:00Z",
            requested_end="2026-10-16T13:00:00+00:00",
        )
        self.assertEqual(capture.parse_utc_instant(start), capture.parse_utc_instant("2026-10-09T22:35:00Z"))
        self.assertEqual(capture.parse_utc_instant(end), capture.parse_utc_instant("2026-10-16T12:50:00+00:00"))
        exact_start, exact_end = capture.effective_run_window(
            {"window": {"start": "2026-10-09T22:00:00+00:00", "end": "2026-10-16T13:00:00Z"}},
            requested_start="2026-10-09T22:00:00Z",
            requested_end="2026-10-16T13:00:00+00:00",
        )
        self.assertEqual(capture.parse_utc_instant(exact_start), capture.parse_utc_instant("2026-10-09T22:00:00Z"))
        self.assertEqual(capture.parse_utc_instant(exact_end), capture.parse_utc_instant("2026-10-16T13:00:00Z"))
        with self.assertRaisesRegex(ValueError, "before the requested"):
            capture.effective_run_window(
                {"window": {"start": "2026-10-09T21:59:00Z", "end": "2026-10-16T12:50:00Z"}},
                requested_start="2026-10-09T22:00:00Z",
                requested_end="2026-10-16T13:00:00Z",
            )
        with self.assertRaisesRegex(ValueError, "ends after the requested"):
            capture.effective_run_window(
                {"window": {"start": "2026-10-09T22:00:00Z", "end": "2026-10-16T13:01:00Z"}},
                requested_start="2026-10-09T22:00:00Z",
                requested_end="2026-10-16T13:00:00Z",
            )
        with self.assertRaises(ValueError):
            capture.effective_run_window(
                {"window": {"start": "not-a-time", "end": "2026-10-16T12:50:00Z"}},
                requested_start=None,
                requested_end=None,
            )
        with self.assertRaisesRegex(ValueError, "changed the frozen"):
            capture.require_same_batch_window(
                "2026-10-09T22:36:00Z", "2026-10-16T12:50:00Z",
                "2026-10-09T22:35:00+00:00", "2026-10-16T12:50:00+00:00",
            )

    def test_batch_receipt_is_atomic_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipts" / "batch-0000.json"
            capture.write_atomic_json(path, {"run_id": "run-test", "rule_ids": ["FC1"]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["run_id"], "run-test")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_receipt_preserves_no_target_status_without_equipment(self) -> None:
        rows = capture.no_applicable_status_rows(
            {
                ("CHW-1", ""): "SKIP_NO_TARGETS",
                ("FC1", "AHU_1"): "FAULT",
                ("VAV-1", "VAV_1"): "NOT_APPLICABLE_EQUIPMENT_TYPE",
            }
        )
        self.assertEqual(
            rows,
            [
                {
                    "rule_id": "CHW-1",
                    "equipment_id": "",
                    "status": "SKIP_NO_TARGETS",
                    "pair_status": "not_applicable",
                },
                {
                    "rule_id": "VAV-1",
                    "equipment_id": "VAV_1",
                    "status": "NOT_APPLICABLE_EQUIPMENT_TYPE",
                    "pair_status": "not_applicable",
                },
            ],
        )


class BatchPersistedScopeValidationTest(unittest.TestCase):
    """Scoped registry persist semantics for batched IP baseline capture."""

    @staticmethod
    def _registry_rule_ids(count: int = 77) -> set[str]:
        return {f"RULE-{index:03d}" for index in range(count)}

    def test_validate_accepts_five_computed_and_seventy_two_carried(self) -> None:
        registry = self._registry_rule_ids()
        batch = {f"RULE-{index:03d}" for index in range(5)}
        carried = registry - batch
        capture.validate_batch_scope_rule_sets(
            computed_rule_ids=set(batch),
            carried_rule_ids=set(carried),
            batch=set(batch),
            registry_rule_ids=registry,
        )

    def test_validate_rejects_carried_rule_that_overlaps_batch(self) -> None:
        registry = self._registry_rule_ids()
        batch = {f"RULE-{index:03d}" for index in range(5)}
        carried = (registry - batch) | {"RULE-000"}
        with self.assertRaisesRegex(ValueError, "overlap"):
            capture.validate_batch_scope_rule_sets(
                computed_rule_ids=set(batch),
                carried_rule_ids=carried,
                batch=set(batch),
                registry_rule_ids=registry,
            )

    def test_validate_rejects_missing_batch_rule(self) -> None:
        registry = self._registry_rule_ids()
        batch = {f"RULE-{index:03d}" for index in range(5)}
        computed = set(batch)
        computed.remove("RULE-004")
        with self.assertRaisesRegex(ValueError, "freshly computed"):
            capture.validate_batch_scope_rule_sets(
                computed_rule_ids=computed,
                carried_rule_ids=registry - batch,
                batch=set(batch),
                registry_rule_ids=registry,
            )

    def test_fetch_batch_run_rule_sets_fake_seventy_seven_rule_cohort(self) -> None:
        registry = self._registry_rule_ids()
        batch = {f"RULE-{index:03d}" for index in range(5)}
        carried = registry - batch
        fetch_rows = [(rule_id, True) for rule_id in sorted(batch | carried)]

        fake_cursor = mock.MagicMock()
        fake_cursor.fetchall.return_value = fetch_rows
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value.__enter__ = mock.Mock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)

        computed, carried_ids = capture.fetch_batch_run_rule_sets(
            fake_conn,
            building_id="SITE_X",
            run_id="run-batch-0",
            batch=set(batch),
        )
        self.assertEqual(computed, batch)
        self.assertEqual(carried_ids, carried)

    def test_assert_no_interleaved_fdd_run_raises(self) -> None:
        marker = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with mock.patch.object(
            capture,
            "interleaved_logical_run_ids",
            return_value=["run-afdd-timer"],
        ):
            with self.assertRaises(capture.CaptureQualificationError) as ctx:
                capture.assert_no_interleaved_fdd_run(
                    mock.MagicMock(),
                    building_id="SITE_X",
                    marker=marker,
                    allowed_run_ids={"run-capture-1"},
                )
        self.assertIn("concurrent_non_capture_fdd_run", str(ctx.exception.reason))

    def test_manifest_records_site_disqualifiers(self) -> None:
        meta = {
            "skip_pandas": False,
            "allow_errors": False,
            "ip_oracle": {"version": "4.4.9"},
            "sites": [
                {
                    "building_id": "SITE_X",
                    "disqualifying_reasons": ["concurrent_non_capture_fdd_run:run-afdd"],
                }
            ],
        }
        reasons = capture.baseline_capture_disqualifiers(meta)
        self.assertIn("concurrent_non_capture_fdd_run:run-afdd", reasons)


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
                    "equipmentId": "AHU_1",
                    "pointId": "portal-dsp",
                    "column": "dsp",
                    "fddSelection": "duct-static-pressure",
                    "openfdd_key": "AHU_1.dsp",
                },
            ],
        ):
            with mock.patch.object(capture, "resolve_bound_openfdd_key", return_value="AHU_1.dsp"):
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
        # The frozen registry predates the optional cookbook annotation; the
        # Python rule catalog is the authoritative implementation oracle.
        fc1_rules[0].pop("pandas_function", None)

        building_id = "SYNTH_PANDAS_CAPTURE"
        window_start = "2026-06-01T00:00:00Z"
        window_end = "2026-06-01T06:00:00Z"
        idx = pd.date_range("2026-06-01", periods=24, freq="5min", tz="UTC")

        sparql_points = [
            {"equipmentId": "AHU_1", "pointId": "dsp-id", "column": "dsp", "fddSelection": "duct-static-pressure", "openfdd_key": "AHU_1.dsp"},
            {
                "equipmentId": "AHU_1", "pointId": "dsps-id", "column": "dsps",
                "fddSelection": "duct-static-pressure-sp",
                "openfdd_key": "AHU_1.dsps",
            },
            {"equipmentId": "AHU_1", "pointId": "fc-id", "column": "fc", "fddSelection": "fan-cmd", "openfdd_key": "AHU_1.fc"},
            {"equipmentId": "AHU_1", "pointId": "fs-id", "column": "fs", "fddSelection": "fan-status", "openfdd_key": "AHU_1.fs"},
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
                capture, "resolve_bound_openfdd_key",
                side_effect=lambda _conn, *, point, **_kw: point.get("openfdd_key"),
            ):
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
            with mock.patch.object(
                capture,
                "resolve_bound_openfdd_key",
                side_effect=lambda _conn, *, point, **_kwargs: point.get("openfdd_key"),
            ):
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
                "openfdd_key": "RTU_A.fc",
            },
        ]
        seen: list[str] = []

        def fake_load(_conn, *, openfdd_key, **_kwargs):
            seen.append(openfdd_key)
            import pandas as pd

            idx = pd.date_range("2026-06-01", periods=2, freq="5min", tz="UTC")
            return [(ts, 1.0) for ts in idx]

        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(
                capture, "resolve_bound_openfdd_key",
                side_effect=lambda _conn, *, point, **_kw: point.get("openfdd_key"),
            ):
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

    def test_unmapped_optional_role_skipped_frame_still_builds(self) -> None:
        points = [
            {
                "equipmentId": "RTU_A",
                "column": "fc",
                "fddSelection": "fan_cmd",
                "openfdd_key": "RTU_A.fc",
            },
            {
                "equipmentId": "RTU_A",
                "column": "mystery",
                "fddSelection": "not_in_golden_xyz",
            },
        ]
        frame, skips = self._frame_from_points(
            "RTU_A",
            points,
            load_keys={capture.resolve_openfdd_key("RTU_A", "fc", "RTU_A.fc")},
        )
        self.assertEqual(skips["skipped_unmapped_role"], 1)
        self.assertIn("fan-cmd", frame.columns)

    def test_unmapped_required_role_pair_status(self) -> None:
        fc1_rules = [r for r in capture.load_rule_registry() if r.get("rule_id") == "FC1"]
        self.assertEqual(len(fc1_rules), 1)
        rule = dict(fc1_rules[0])
        rule["required_roles"] = list(rule.get("required_roles") or []) + ["not_in_golden_xyz"]
        points = [
            {"equipmentId": "RTU_A", "column": "fc", "fddSelection": "fan_cmd"},
        ]
        http = mock.MagicMock()
        http.get_json.return_value = {
            "equipment": [{"equipment_id": "RTU_A", "equip_type": "ahu"}],
        }
        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(capture, "load_samples_in_window", return_value=[]):
                rows, _cov, _err, _skips = capture.collect_pandas_fdd_rows(
                    http,
                    {},
                    mock.MagicMock(),
                    building_id="SITE_GEN",
                    rules=[rule],
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-01T06:00:00Z",
                    pandas_max_rules=None,
                )
        self.assertTrue(
            any(r.get("pair_status") == "unmapped_role" for r in rows),
            rows,
        )

    def test_all_points_no_role_error_lists_skip_counters(self) -> None:
        points = [
            {
                "equipmentId": "RTU_A",
                "column": "x1",
                "fddSelection": "",
            },
        ]
        with self.assertRaises(ValueError) as ctx:
            self._frame_from_points("RTU_A", points, load_keys=set())
        self.assertIn("all points skipped", str(ctx.exception))
        self.assertIn("skipped_no_role=1", str(ctx.exception))

    def test_fc1_computes_on_role_id_columns(self) -> None:
        fc1_rules = [r for r in capture.load_rule_registry() if r.get("rule_id") == "FC1"]
        self.assertEqual(len(fc1_rules), 1)
        idx = __import__("pandas").date_range("2026-06-01", periods=24, freq="5min", tz="UTC")
        points = [
            {"equipmentId": "RTU_A", "column": "dsp", "fddSelection": "duct_static", "openfdd_key": "RTU_A.dsp"},
            {"equipmentId": "RTU_A", "column": "dsps", "fddSelection": "duct_static_sp", "openfdd_key": "RTU_A.dsps"},
            {"equipmentId": "RTU_A", "column": "fc", "fddSelection": "fan_cmd", "openfdd_key": "RTU_A.fc"},
            {"equipmentId": "RTU_A", "column": "fs", "fddSelection": "fan_status", "openfdd_key": "RTU_A.fs"},
        ]

        def fake_load(_conn, *, openfdd_key, **_kwargs):
            val = 1.5 if openfdd_key.endswith(".dsps") else 1.0
            return [(ts, val) for ts in idx]

        http = mock.MagicMock()
        http.get_json.return_value = {
            "equipment": [{"equipment_id": "RTU_A", "equip_type": "ahu"}],
        }
        with mock.patch.object(capture, "post_sparql", return_value=points):
            with mock.patch.object(
                capture, "resolve_bound_openfdd_key",
                side_effect=lambda _conn, *, point, **_kw: point.get("openfdd_key"),
            ):
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


class TelemetryReadOnlyGuardTest(unittest.TestCase):
    def test_sample_count_respects_window_end(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchone.side_effect = [(100,), (4,), (4,)]

        counts = capture.telemetry_row_counts(
            conn,
            "SITE_A",
            sample_before="2026-10-15T00:00:00Z",
        )
        self.assertEqual(counts["sample"], 100)
        sample_sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("ts <", sample_sql)

    def test_live_ingest_after_window_does_not_change_guard_count(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchone.side_effect = [(100,), (4,), (4,), (100,), (4,), (4,)]

        before = capture.telemetry_row_counts(
            conn, "SITE_A", sample_before="2026-10-15T00:00:00Z"
        )
        after = capture.telemetry_row_counts(
            conn, "SITE_A", sample_before="2026-10-15T00:00:00Z"
        )
        self.assertEqual(before, after)

    def test_write_inside_window_changes_guard_count(self) -> None:
        conn = mock.MagicMock()
        cur = mock.MagicMock()
        conn.cursor.return_value.__enter__ = mock.Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        cur.fetchone.side_effect = [(100,), (4,), (4,), (101,), (4,), (4,)]

        before = capture.telemetry_row_counts(
            conn, "SITE_A", sample_before="2026-10-15T00:00:00Z"
        )
        after = capture.telemetry_row_counts(
            conn, "SITE_A", sample_before="2026-10-15T00:00:00Z"
        )
        self.assertNotEqual(before["sample"], after["sample"])


class SqlDailyRollupTest(unittest.TestCase):
    def test_legacy_window_fraction_spread_is_equal_per_full_day(self) -> None:
        """Document the pre-fix ``distribute_interval_buckets`` symptom (P0 equal per day)."""
        window_days = 5
        total_fault_seconds = 24477.7
        per_day = total_fault_seconds / window_days
        self.assertAlmostEqual(per_day, 4895.54, places=1)

    def test_fault_on_single_day_only(self) -> None:
        import pandas as pd

        start = pd.Timestamp("2026-10-10T08:00:00Z", tz="UTC")
        idx = pd.date_range(start, periods=8, freq="5min", tz="UTC")
        idx2 = pd.date_range(start + pd.Timedelta(days=1), periods=8, freq="5min", tz="UTC")
        full = idx.union(idx2)
        confirmed = pd.Series(False, index=full)
        confirmed.iloc[2:6] = True
        fault_by_day, _ = capture.daily_fault_and_covered_seconds(
            confirmed, full, poll_seconds=300.0
        )
        self.assertGreater(fault_by_day.get("2026-10-10", 0.0), 0.0)
        self.assertEqual(fault_by_day.get("2026-10-11", 0.0), 0.0)


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
