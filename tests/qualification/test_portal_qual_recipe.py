"""Disposable portal qualification recipe: Docker-free checks for CI.

Covers the pure helpers (plan, secrets, packages, provider config, verdict),
the loopback NF emulator in-process, and static guarantees of the shell
recipes and compose overlay (syntax, shellcheck, no local builds, no
`down -v` / prune, no open-bind escape hatch, no MQTT wiring).
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUAL = ROOT / "scripts" / "qualification"
sys.path.insert(0, str(QUAL / "portal"))

import nf_emulator  # noqa: E402
import portal_qual  # noqa: E402

OVERLAY = ROOT / "docker" / "compose.portal-qual.yml"
LIB = QUAL / "lib" / "portal_stack.sh"
RECIPES = [
    QUAL / "run_portal_qualification.sh",
    QUAL / "restore_to_empty.sh",
    QUAL / "run_isolated_zap_af.sh",
    QUAL / "run_wave_c_isolated.sh",
]
SHELL_FILES = [LIB, *RECIPES]
PREFIX = "qa20261022ab12"


class PortalQualHelpersTest(unittest.TestCase):
    def test_prefix_is_dated_and_unique_shape(self):
        p = portal_qual.new_prefix(dt.date(2026, 10, 22), suffix="ab12")
        self.assertEqual(p, PREFIX)
        self.assertRegex(portal_qual.new_prefix(), r"^qa[0-9]{8}[a-z0-9]{4}$")
        with self.assertRaises(ValueError):
            portal_qual.new_prefix(dt.date(2026, 10, 22), suffix="X!")

    def test_secret_is_long_and_random(self):
        a, b = portal_qual.new_secret(), portal_qual.new_secret()
        self.assertGreaterEqual(len(a), 48)
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            portal_qual.new_secret(16)

    def test_project_name_is_scoped(self):
        name = portal_qual.project_name("portal", PREFIX)
        self.assertEqual(name, f"openfdd-qual-portal-{PREFIX}")
        with self.assertRaises(ValueError):
            portal_qual.project_name("Bad Kind", PREFIX)

    def test_plan_two_tenants_viewer_operator_each(self):
        plan = portal_qual.build_plan(PREFIX)
        a, b = plan["tenants"]["a"], plan["tenants"]["b"]
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(all(t["id"].startswith(PREFIX) for t in (a, b)))
        self.assertFalse(set(a["building_ids"]) & set(b["building_ids"]))
        roles = {(u["tenant_ids"][0], u["role"]) for u in plan["users"]}
        self.assertEqual(
            roles,
            {(a["id"], "operator"), (a["id"], "viewer"), (b["id"], "operator"), (b["id"], "viewer")},
        )
        for u in plan["users"]:
            self.assertTrue(u["username"].startswith(PREFIX))
            self.assertNotIn("password", u)
        self.assertEqual(plan["tenant_admin_probe"]["expected_status"], 400)
        self.assertIn(plan["nf"]["building_id"], a["building_ids"])

    def test_package_zip_is_deterministic_openfdd_package(self):
        raw = portal_qual.package_zip("SITE_A", "AHU_A", rows=10)
        self.assertEqual(raw, portal_qual.package_zip("SITE_A", "AHU_A", rows=10))
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            point_map = json.loads(zf.read("AHU_A/history_wide.json"))
            csv_lines = zf.read("AHU_A/history_wide.csv").decode().splitlines()
        self.assertEqual(manifest["schema_version"], "openfdd_package_v1")
        self.assertEqual(manifest["building_id"], "SITE_A")
        self.assertEqual(point_map["equipType"], "ahu")
        self.assertEqual(len(csv_lines), 11)
        with self.assertRaises(ValueError):
            portal_qual.package_zip("SITE A; rm", "AHU_A")

    def test_provider_sites_reach_only_the_loopback_emulator(self):
        plan = portal_qual.build_plan(PREFIX)
        sites = portal_qual.provider_sites(plan)
        portal_qual.assert_emulator_only(sites)
        (site,) = sites
        self.assertEqual(site["endpoint"], "http://127.0.0.1:18089")
        self.assertEqual(site["auth_mode"], "anonymous")
        self.assertEqual(site["tenant_id"], plan["tenants"]["a"]["id"])
        self.assertNotIn("client_secret", site)
        fixture = nf_emulator.load_fixture(portal_qual.NF_FIXTURE)
        self.assertEqual(
            {p["provider_point_id"] for p in site["point_map"]},
            {p["uuid"] for p in fixture["points"]},
        )
        bad = [dict(site, endpoint="https://portal.example.com")]
        with self.assertRaises(ValueError):
            portal_qual.assert_emulator_only(bad)
        with self.assertRaises(ValueError):
            portal_qual.assert_emulator_only([dict(site, client_secret="x")])

    def test_probe_config_uses_env_references_only(self):
        plan = portal_qual.build_plan(PREFIX)
        cfg = portal_qual.probe_config(plan, "http://127.0.0.1:43123")
        blob = json.dumps(cfg)
        self.assertNotIn("password\":", blob.replace("password_env\":", ""))
        self.assertEqual(set(cfg["identities"]), {"admin", "operator_a", "viewer_a", "operator_b", "viewer_b"})
        self.assertEqual(cfg["fixtures"]["building_a"], plan["tenants"]["a"]["site"])
        self.assertEqual(cfg["origin_allowlist"], ["http://127.0.0.1:43123"])

    def test_probe_config_loads_in_security_harness(self):
        sys.path.insert(0, str(ROOT / "scripts" / "security"))
        from openfdd_security.config import load_config

        plan = portal_qual.build_plan(PREFIX)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cfg.json"
            path.write_text(json.dumps(portal_qual.probe_config(plan, "http://127.0.0.1:43123")))
            cfg = load_config(path)
        self.assertEqual(cfg.fixtures.tenant_b, plan["tenants"]["b"]["id"])
        self.assertIn("viewer_a", cfg.identities)

    def test_verdict_requires_every_step_pass(self):
        steps = [{"id": "a", "status": "PASS"}, {"id": "b", "status": "PASS"}]
        self.assertEqual(portal_qual.verdict(steps, ["a", "b"], "s")["status"], "PASS")
        failed = portal_qual.verdict(steps + [{"id": "c", "status": "FAIL"}], ["a", "c"], "s")
        self.assertEqual((failed["status"], failed["failed_steps"]), ("FAIL", ["c"]))
        missing = portal_qual.verdict(steps, ["a", "z"], "s")
        self.assertEqual((missing["status"], missing["missing_steps"]), ("BLOCKED", ["z"]))
        self.assertEqual(portal_qual.verdict(steps, [], "s")["status"], "BLOCKED")
        dup = portal_qual.verdict(steps + [{"id": "a", "status": "PASS"}], ["a"], "s")
        self.assertEqual(dup["status"], "FAIL")

    def test_cli_secret_not_echoed_elsewhere(self):
        out = subprocess.run(
            [sys.executable, "-B", str(QUAL / "portal" / "portal_qual.py"), "secret", "--bytes", "48"],
            capture_output=True, text=True, check=True,
        )
        self.assertGreaterEqual(len(out.stdout), 48)
        self.assertEqual(out.stderr, "")
        self.assertNotIn("\n", out.stdout)


class NfEmulatorTest(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 22, 12, 3, 17, tzinfo=dt.timezone.utc)

    @classmethod
    def setUpClass(cls):
        cls.fixture = nf_emulator.load_fixture(nf_emulator.DEFAULT_FIXTURE)
        handler = nf_emulator.make_handler(cls.fixture, clock=lambda: cls.NOW)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_token_and_point_query(self):
        status, token = self._call("POST", "/api/v1/auth/token", {})
        self.assertEqual(status, 200)
        self.assertIn("accessToken", token)
        status, body = self._call("POST", "/api/v1/point/query", {"pageSize": 100})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["points"]), len(self.fixture["points"]))
        for p in body["points"]:
            self.assertEqual(p["latestValue"]["ts"], "2026-10-22T12:00:00Z")
            self.assertIsInstance(p["latestValue"]["double"], float)

    def test_history_replays_on_grid_and_caps_at_now(self):
        uuid = self.fixture["points"][0]["uuid"]
        end = int(self.NOW.timestamp()) + 3600
        start = int(self.NOW.timestamp()) - 3600
        status, body = self._call(
            "GET", f"/api/v1/point/data?from.seconds={start}&to.seconds={end}&uuids={uuid}"
        )
        self.assertEqual(status, 200)
        (series,) = body["data"]
        stamps = [v["ts"] for v in series["values"]]
        self.assertEqual(stamps[-1], "2026-10-22T12:00:00Z")
        self.assertEqual(len(stamps), 12)
        self.assertEqual(stamps, sorted(stamps))

    def test_history_rejects_unbounded_window(self):
        now = int(self.NOW.timestamp())
        status, _ = self._call("GET", f"/api/v1/point/data?from.seconds={now - 30 * 86400}&to.seconds={now}")
        self.assertEqual(status, 400)

    def test_point_write_is_refused(self):
        status, body = self._call("POST", "/api/v1/point/data", {"uuid": "x", "value": 1})
        self.assertEqual(status, 405)
        self.assertIn("not emulated", body["error"])

    def test_refuses_non_loopback_bind(self):
        nf_emulator.require_loopback("127.0.0.1")
        nf_emulator.require_loopback("::1")
        with self.assertRaises(SystemExit):
            nf_emulator.require_loopback("0.0.0.0")
        with self.assertRaises(SystemExit):
            nf_emulator.require_loopback("10.0.0.5")

    def test_fixture_carries_no_real_credentials(self):
        text = nf_emulator.DEFAULT_FIXTURE.read_text()
        self.assertNotRegex(text.lower(), r"client_secret|https?://(?!127\.0\.0\.1)")


class RecipeStaticTest(unittest.TestCase):
    def test_bash_syntax(self):
        for path in SHELL_FILES:
            with self.subTest(path=path.name):
                subprocess.run(["bash", "-n", str(path)], check=True)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck(self):
        subprocess.run(
            ["shellcheck", "-x", *[str(p) for p in SHELL_FILES]],
            check=True, cwd=QUAL,
        )

    def test_recipes_are_executable(self):
        for path in RECIPES:
            with self.subTest(path=path.name):
                self.assertTrue(path.stat().st_mode & 0o111, f"{path.name} not executable")

    def test_no_destructive_or_shared_teardown(self):
        for path in SHELL_FILES:
            text = path.read_text()
            code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
            with self.subTest(path=path.name):
                self.assertNotRegex(code, r"down\s+[^\n]*-v\b")
                self.assertNotRegex(code, r"down\s+[^\n]*--volumes")
                self.assertNotRegex(code, r"(volume|system|image|container|network)\s+prune")
                self.assertNotIn("OPENFDD_RESET_DB", code)
                self.assertNotIn("OPENFDD_ALLOW_DESTRUCTIVE_DB", code)
                self.assertNotIn("OPENFDD_ALLOW_OPEN_BIND=1", code)
                self.assertNotIn("RANDOM", code)
                # Forbidden-service probes may name OT services; wiring may not.
                self.assertNotRegex(code.lower(), r"openfdd_mqtt|mqtts|fieldbus_|bacnet_|openfdd-mqtt")
                self.assertNotRegex(code, r"docker (compose [^\n]*)?build\b")
                self.assertNotIn("railway", code.lower())

    def test_volume_removal_is_project_scoped(self):
        text = LIB.read_text()
        self.assertIn('label=com.docker.compose.project=${PORTAL_PROJECT}', text)
        self.assertIn('"$vol" == "${PORTAL_PROJECT}_"*', text)
        self.assertIn("^openfdd-qual-[a-z0-9-]+$", text)
        self.assertIn("up -d --no-build", text)

    def test_secrets_stay_out_of_argv(self):
        text = LIB.read_text()
        self.assertIn('-H "@$PORTAL_PRIV/hdr.$ident"', text)
        self.assertIn('--data-binary "@$body"', text)
        self.assertIn('--env-file "$PORTAL_PRIV/stack.env"', text)
        self.assertIn('chmod 700 "$PORTAL_PRIV"', text)
        self.assertIn("umask 077", text)
        for path in SHELL_FILES:
            code = path.read_text()
            with self.subTest(path=path.name):
                self.assertNotRegex(code, r'-e\s+OPENFDD_(JWT_SECRET|ADMIN_PASSWORD)=')
                self.assertNotRegex(code, r'Authorization: Bearer \$\{?TOKEN')
                self.assertNotRegex(code, r'"password":"\$\{?')

    def test_overlay_pins_ghcr_and_isolates_network(self):
        text = "\n".join(
            l for l in OVERLAY.read_text().splitlines() if not l.lstrip().startswith("#")
        )
        self.assertNotRegex(text, r"(?m)^\s*build:", "overlay must not build images")
        self.assertIn("ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:?", text)
        self.assertIn("ghcr.io/bbartling/openfdd-web:${OPENFDD_IMAGE_TAG:?", text)
        self.assertIn('OPENFDD_MULTI_TENANT: "1"', text)
        self.assertIn('OPENFDD_ALLOW_OPEN_BIND: ""', text)
        self.assertRegex(text, r"qual-private:\s*\n\s*internal: true")
        self.assertIn('network_mode: "service:central"', text)
        self.assertIn("qual-workspace:/workspace", text)
        self.assertNotIn("../workspace", text)
        self.assertRegex(text, r"python:3\.12-alpine@sha256:[0-9a-f]{64}")
        self.assertNotRegex(text.lower(), r"mqtt|fieldbus|bacnet")
        # Central and Timescale publish nothing; web only on loopback.
        self.assertEqual(text.count("ports: !reset []"), 2)
        self.assertIn('"127.0.0.1:${PORTAL_QUAL_WEB_PORT', text)

    def test_overlay_parses_as_yaml_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")

        class Loader(yaml.SafeLoader):
            pass

        for tag in ("!reset", "!override"):
            Loader.add_constructor(tag, lambda loader, node: (
                loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
                else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
                else loader.construct_scalar(node)
            ))
        doc = yaml.load(OVERLAY.read_text(), Loader=Loader)
        self.assertEqual(set(doc["services"]), {"central", "timescale", "web", "nf-emulator"})
        self.assertEqual(doc["services"]["nf-emulator"]["profiles"], ["nf"])

    def test_wave_c_points_at_portal_profile(self):
        text = (QUAL / "run_wave_c_isolated.sh").read_text()
        self.assertIn("run_portal_qualification.sh", text)
        self.assertIn('deployment_profile: "cloud_portal"', text)
        self.assertNotIn("mqtts_transport_isolation", text)

    def test_restore_proves_historian_and_identity(self):
        text = (QUAL / "restore_to_empty.sh").read_text()
        for needle in (
            "pg_dump -U openfdd -d openfdd -Fc",
            "timescaledb_pre_restore",
            "timescaledb_post_restore",
            "portal_site_fingerprint",
            "restore.timescale_fixture_site",
            "restore.timescale_total",
            "restore.control_plane_api",
            "restore.control_plane_files",
            "restore.operator_login",
            "restore.workspace_manifest",
            "portal_remove_project_volumes",
        ):
            self.assertIn(needle, text)
        self.assertNotIn("waveC_restore_marker", text)

    def test_portal_recipe_required_steps_are_emitted(self):
        text = (QUAL / "run_portal_qualification.sh").read_text()
        required = text.split("--required", 1)[1].split("VERDICT_RC", 1)[0]
        ids = re.findall(r"[a-z_]+\.[a-z_.$A-Z{}]+", required)
        self.assertGreater(len(ids), 15)
        emitted = text.split("--required", 1)[0]
        for sid in ids:
            literal = sid.split("$", 1)[0]
            templated = re.sub(r"_[ab]$", "_$side", sid)
            with self.subTest(step=sid):
                self.assertTrue(
                    f"portal_step {sid} " in emitted
                    or f'portal_step "{templated}"' in emitted
                    or (literal != sid and f'"{literal}' in emitted),
                    sid,
                )


if __name__ == "__main__":
    unittest.main()
