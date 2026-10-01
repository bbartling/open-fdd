"""Wave I/K MEGA gates query the live MQTT building ACME.

`bldg2` is equipment (`bldg2-zone-loopback`), not a hub building id.
BAS/MQTT `oa_t` is probed on AHU `rtu_01` (`OPENFDD_WAVE_MQTT_OA_EQ`).
Missing AV columns stay field-catalog Soft-OPEN and still fail the gate.
A mapped column with no values is a product fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
WAVE_I = ROOT / "scripts/nightly-ot-bench/20_wave_i_app_test_megas.sh"
WAVE_K = ROOT / "scripts/nightly-ot-bench/21_wave_k_app_test_megas.sh"

LOOPBACK = "bldg2-zone-loopback"
OA_EQ = "rtu_01"
WEATHER = "hosted-weather"


class _Hub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        self.server.hits.append(("GET", parsed.path, qs, None))  # type: ignore[attr-defined]
        if parsed.path == "/api/auth/status":
            self._send({"auth_required": False})
            return
        if parsed.path == "/api/csv/import/package/mapping":
            self._send(self._mapping(qs))
            return
        self._send({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        parsed = urlparse(self.path)
        self.server.hits.append(("POST", parsed.path, {}, body))  # type: ignore[attr-defined]
        mode = self.server.mode  # type: ignore[attr-defined]
        if parsed.path == "/api/fdd/run":
            self._send({"ok": True, "results": []})
            return
        if parsed.path == "/api/analytics/sensor-faults":
            self._send(
                {
                    "analytics": {
                        "coverage": {"matched_equipment_count": 2},
                        "rows": [{"equipment_id": "AHU_1"}],
                    }
                }
            )
            return
        if parsed.path == "/api/analytics/bas-vs-web-oat":
            self._send(
                {
                    "analytics": {
                        "points": [],
                        "warnings": [
                            "BAS vs web OAT unavailable — need distinct oa_t and web OAT"
                        ],
                    }
                }
            )
            return
        if parsed.path == "/api/analytics/inspect":
            self._send(self._inspect(body, mode))
            return
        self._send({"ok": False, "error": "not found"}, status=404)

    def _mapping(self, qs: dict) -> dict:
        building = (qs.get("building_id") or [""])[0]
        equipment = (qs.get("equipment_id") or [""])[0]
        if building == "BUILDING_100":
            return {
                "ok": False,
                "error": f"equipment {equipment!r} not found under historian building BUILDING_100",
                "building_id": building,
            }
        if building != "ACME":
            return {
                "ok": False,
                "error": f'building "{building}" not found under csv_buildings and no historian equipment',
                "hint": "upload an openfdd_package_v1 zip or wait for MQTT ingest",
                "building_id": building,
            }
        column = {"column": "timestamp_utc", "role": "timestamp_utc", "status": "mapped"}
        return {
            "ok": True,
            "building_id": "ACME",
            "equipment_ids": [LOOPBACK, OA_EQ, WEATHER],
            "equipment": [
                {
                    "equipment_id": LOOPBACK,
                    "columns": [column],
                    "roles": {"timestamp_utc": "timestamp_utc"},
                },
                {
                    "equipment_id": OA_EQ,
                    "columns": [column],
                    "roles": {"timestamp_utc": "timestamp_utc"},
                },
                {
                    "equipment_id": WEATHER,
                    "columns": [column],
                    "roles": {"timestamp_utc": "timestamp_utc"},
                },
            ],
        }

    def _inspect(self, body: dict, mode: str) -> dict:
        ids = body.get("equipment_ids") or []
        if body.get("building_id") == "BUILDING_100" and ids == ["AHU_1"]:
            return {
                "analytics": {
                    "points": [
                        {"timestamp_utc": "2026-03-01T00:00:00Z", "sat": 55},
                        {"timestamp_utc": "2026-07-15T00:00:00Z", "sat": 60},
                    ]
                }
            }
        columns: list[str] = []
        point: dict = {"timestamp_utc": "2026-09-30T00:00:00Z"}
        if mode == "column_present_null" and LOOPBACK in ids:
            columns = ["zone_t", "zone_rh"]
            point.update({"zone_t": None, "zone_rh": None})
        if mode == "column_present_null" and OA_EQ in ids:
            columns = ["oa_t"]
            point["oa_t"] = None
        if mode == "column_present_null" and WEATHER in ids:
            columns = ["web_oa_t"]
            point["web_oa_t"] = None
        if mode == "oa_absent_zone_present" and LOOPBACK in ids:
            return {
                "analytics": {
                    "coverage": {"plottable_columns": ["zone_t"]},
                    "points": [{"timestamp_utc": "2026-09-30T00:00:00Z", "zone_t": 72.0}],
                }
            }
        if mode == "oa_absent_zone_present" and OA_EQ in ids:
            return {
                "analytics": {
                    "coverage": {"plottable_columns": []},
                    "points": [{"timestamp_utc": "2026-09-30T00:00:00Z"}],
                }
            }
        if mode == "oa_absent_zone_present" and WEATHER in ids:
            return {
                "analytics": {
                    "coverage": {"plottable_columns": []},
                    "points": [{"timestamp_utc": "2026-09-30T00:00:00Z"}],
                }
            }
        return {
            "analytics": {
                "coverage": {"plottable_columns": columns},
                "points": [point],
            }
        }

    def _send(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _serve(mode: str) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hub)
    server.hits = []  # type: ignore[attr-defined]
    server.mode = mode  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def _run(script: Path, art: Path, base: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RAILWAY_ONLY"] = "1"
    env["CENTRAL_BASE"] = base
    env["ARTIFACT_DIR"] = str(art)
    env.pop("OPENFDD_WAVE_MQTT_BUILDING", None)
    env.pop("OPENFDD_ADMIN_PASSWORD", None)
    env.pop("RAILWAY_ADMIN_PASSWORD", None)
    return subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _building_ids(server: ThreadingHTTPServer) -> list[str]:
    found: list[str] = []
    for _method, path, qs, body in server.hits:  # type: ignore[attr-defined]
        if path == "/api/auth/status":
            continue
        if qs.get("building_id"):
            found.append(qs["building_id"][0])
        elif isinstance(body, dict) and body.get("building_id"):
            found.append(str(body["building_id"]))
    return found


class WaveIkAcmeBuildingTests(unittest.TestCase):
    def test_scripts_do_not_hardcode_bldg2_as_building(self) -> None:
        for path in (WAVE_I, WAVE_K):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('building_id=bldg2', text)
            self.assertNotIn('"building_id":"bldg2"', text)
            self.assertIn('OPENFDD_WAVE_MQTT_BUILDING:-ACME', text)
            self.assertIn("bldg2-zone-loopback", text)
            self.assertIn("record_soft", text)

    def test_absent_columns_are_soft_open_on_acme(self) -> None:
        server, base = _serve("columns_absent")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                art = Path(tmp)
                wave_i = _run(WAVE_I, art / "i", base)
                wave_k = _run(WAVE_K, art / "k", base)
                self.assertEqual(wave_i.returncode, 1, wave_i.stderr + wave_i.stdout)
                self.assertEqual(wave_k.returncode, 1, wave_k.stderr + wave_k.stdout)
                summary_i = json.loads((art / "i" / "wave_i_app_test_megas.json").read_text())
                summary_k = json.loads((art / "k" / "wave_k_app_test_megas.json").read_text())
                self.assertEqual(summary_i["product_fail"], 0)
                self.assertEqual(summary_i["field_catalog_soft_open"], 4)
                self.assertEqual(summary_i["fail"], 1)
                self.assertEqual(summary_k["product_fail"], 0)
                self.assertEqual(summary_k["field_catalog_soft_open"], 4)
                self.assertEqual(summary_k["fail"], 1)
                log_i = (art / "i" / "wave_i_app_test_megas.log").read_text()
                log_k = (art / "k" / "wave_k_app_test_megas.log").read_text()
                self.assertIn("mapping_acme ok=1 building=ACME", log_i)
                self.assertIn("inspect_zone_t ok=0 soft_open=1", log_i)
                self.assertIn("bas_oa_t ok=0 soft_open=1", log_i)
                self.assertIn("bas_web_oa_t ok=0 soft_open=1", log_i)
                self.assertIn("bas_vs_web_acme ok=0 soft_open=1", log_i)
                self.assertIn("mapping_acme_roles ok=1 building=ACME", log_k)
                self.assertIn("mqtt_zone_t ok=0 soft_open=1", log_k)
                self.assertIn("mqtt_oa_t ok=0 soft_open=1", log_k)
                self.assertIn("mqtt_zone_rh ok=0 soft_open=1", log_k)
                self.assertIn("mqtt_web_oa_t ok=0 soft_open=1", log_k)
                self.assertIn("mapping_cross_site ok=1", log_k)
                buildings = _building_ids(server)
                self.assertIn("ACME", buildings)
                self.assertIn("LAKESIDE_ES", buildings)
                self.assertIn("BUILDING_100", buildings)
                self.assertNotIn("bldg2", buildings)
        finally:
            server.shutdown()
            server.server_close()

    def test_present_null_column_is_product_fail(self) -> None:
        server, base = _serve("column_present_null")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                art = Path(tmp)
                wave_i = _run(WAVE_I, art / "i", base)
                wave_k = _run(WAVE_K, art / "k", base)
                self.assertEqual(wave_i.returncode, 1, wave_i.stderr + wave_i.stdout)
                self.assertEqual(wave_k.returncode, 1, wave_k.stderr + wave_k.stdout)
                summary_i = json.loads((art / "i" / "wave_i_app_test_megas.json").read_text())
                summary_k = json.loads((art / "k" / "wave_k_app_test_megas.json").read_text())
                self.assertEqual(summary_i["product_fail"], 1)
                self.assertEqual(summary_k["product_fail"], 1)
                log_i = (art / "i" / "wave_i_app_test_megas.log").read_text()
                log_k = (art / "k" / "wave_k_app_test_megas.log").read_text()
                self.assertIn("inspect_zone_t ok=0 zone_t column present", log_i)
                self.assertNotIn("inspect_zone_t ok=0 soft_open=1", log_i)
                self.assertIn("bas_oa_t ok=0 oa_t column present", log_i)
                self.assertIn("bas_web_oa_t ok=0 web_oa_t column present", log_i)
                self.assertNotIn("bas_oa_t ok=0 soft_open=1", log_i)
                self.assertNotIn("bas_web_oa_t ok=0 soft_open=1", log_i)
                self.assertIn("mqtt_zone_t ok=0 zone_t column present", log_k)
                self.assertIn("mqtt_oa_t ok=0 oa_t column present", log_k)
                self.assertNotIn("mqtt_zone_t ok=0 soft_open=1", log_k)
                self.assertNotIn("mqtt_oa_t ok=0 soft_open=1", log_k)
                self.assertNotIn("bldg2", _building_ids(server))
        finally:
            server.shutdown()
            server.server_close()

    def test_oa_absent_does_not_hide_a_zone_value(self) -> None:
        """zone_t with values stays a product pass when oa_t is field-catalog."""
        server, base = _serve("oa_absent_zone_present")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                art = Path(tmp)
                wave_i = _run(WAVE_I, art / "i", base)
                wave_k = _run(WAVE_K, art / "k", base)
                self.assertEqual(wave_i.returncode, 1, wave_i.stderr + wave_i.stdout)
                self.assertEqual(wave_k.returncode, 1, wave_k.stderr + wave_k.stdout)
                summary_i = json.loads((art / "i" / "wave_i_app_test_megas.json").read_text())
                summary_k = json.loads((art / "k" / "wave_k_app_test_megas.json").read_text())
                self.assertEqual(summary_i["product_fail"], 0)
                self.assertGreaterEqual(summary_i["field_catalog_soft_open"], 1)
                self.assertEqual(summary_k["product_fail"], 0)
                log_i = (art / "i" / "wave_i_app_test_megas.log").read_text()
                log_k = (art / "k" / "wave_k_app_test_megas.log").read_text()
                self.assertIn("inspect_zone_t ok=1", log_i)
                self.assertIn("bas_oa_t ok=0 soft_open=1", log_i)
                self.assertIn("bas_web_oa_t ok=0 soft_open=1", log_i)
                self.assertNotIn("bas_oa_t ok=1", log_i)
                self.assertIn("mqtt_zone_t ok=1", log_k)
                self.assertIn("mqtt_oa_t ok=0 soft_open=1", log_k)
                self.assertNotIn("mqtt_oa_t ok=1", log_k)
                self.assertNotIn("mqtt_zone_t ok=0 soft_open=1", log_k)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
