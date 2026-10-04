"""Real gate 25 / 25b / 26 wrappers must refuse a false green.

These tests execute the shell scripts. A PATH python stub stands in for the
probe or MQTT observer so the run never contacts Railway, ACME, or a broker.
Sabotage is a stale PASS artifact, a FAIL observer with exit 0, a contradictory
ok/status pair, or transport ERROR checks labeled BLOCKED.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.evidence import CheckResult, SecurityReport, write_report  # noqa: E402
from openfdd_security.profiles import required_check_ids  # noqa: E402

GATE25 = ROOT / "scripts/nightly-ot-bench/25_security_python_harness.sh"
GATE25B = ROOT / "scripts/nightly-ot-bench/25b_security_post_stress.sh"
GATE26 = ROOT / "scripts/nightly-ot-bench/26_security_mqtt_acl.sh"
LIB = ROOT / "scripts/nightly-ot-bench/lib_security_gate.sh"
EXAMPLE = ROOT / "scripts/security/config/example_security_fixtures.json"

_FAKE_PY = textwrap.dedent(
    """\
    #!/bin/bash
    real=/usr/bin/python3
    joined="$*"
    if [[ "$joined" == *openfdd_security_probe.py* || "$joined" == *mqtt_tenant_acl_observer.py* ]]; then
      out=""
      prev=""
      for a in "$@"; do
        if [[ "$prev" == "--output-dir" || "$prev" == "--out-dir" ]]; then
          out="$a"
        fi
        prev="$a"
      done
      mode="${OPENFDD_WRAPPER_SABOTAGE:-}"
      template="${OPENFDD_SABOTAGE_TEMPLATE:-}"
      dest=""
      if [[ "$joined" == *openfdd_security_probe.py* ]]; then
        dest="$out/security_report.json"
      else
        dest="$out/mqtt_acl_observer.json"
      fi
      case "$mode" in
        stale-pass)
          exit 0
          ;;
        copy-template)
          mkdir -p "$out"
          cp "$template" "$dest"
          if [[ -n "${OPENFDD_SABOTAGE_RC:-}" ]]; then
            exit "$OPENFDD_SABOTAGE_RC"
          fi
          exit 0
          ;;
        observer-fail-rc0|observer-contradict)
          mkdir -p "$out"
          cp "$template" "$out/mqtt_acl_observer.json"
          exit 0
          ;;
      esac
      echo "unhandled sabotage mode: $mode" >&2
      exit 99
    fi
    if [[ "$joined" == *"-m unittest"* ]]; then
      exit 0
    fi
    exec "$real" "$@"
    """
)


def _qualifying_report(directory: Path) -> None:
    report = SecurityReport(
        profile="live_readonly",
        executed=True,
        dry_run=False,
        full_profile=True,
        suites=["X", "Y", "Z"],
    )
    for cid in required_check_ids("live_readonly", ["X", "Y", "Z"]):
        report.add(
            CheckResult(check_id=cid, suite=cid[0].upper(), status="PASS", title=cid)
        )
    write_report(report, directory)


def _error_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "openfdd_security_report_v1",
                "profile": "live_readonly",
                "executed": True,
                "dry_run": False,
                "full_profile": True,
                "overall_status": "BLOCKED",
                "fully_qualified": False,
                "counts": {
                    "planned": 1,
                    "pass": 0,
                    "fail": 0,
                    "error": 1,
                    "blocked": 0,
                    "skipped": 0,
                    "not_applicable": 0,
                },
                "checks": [
                    {
                        "check_id": "y.authz.a_own_building_control",
                        "suite": "Y",
                        "status": "ERROR",
                        "title": "A own",
                        "detail": "transport fault: TimeoutError",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


class RealGateWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="openfdd-gate-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        bindir = self.root / "bin"
        bindir.mkdir()
        fake = bindir / "python3"
        fake.write_text(_FAKE_PY, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.bindir = bindir

    def _env(self, art: Path, mode: str, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bindir}{os.pathsep}{env.get('PATH', '')}"
        env["OPENFDD_WRAPPER_SABOTAGE"] = mode
        env["ARTIFACT_DIR"] = str(art)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for key in (
            "OPENFDD_ADMIN_PASSWORD",
            "OPENFDD_AGENT_PASSWORD",
            "RAILWAY_ADMIN_PASSWORD",
            "OPENFDD_JWT_SECRET",
        ):
            env.pop(key, None)
        env.update(extra)
        return env

    def _run(self, script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _verdict(self, art: Path) -> dict:
        path = art / "security_gate_verdict.json"
        self.assertTrue(path.is_file(), f"missing verdict in {art}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_gate25_stale_pass_report_is_not_green(self) -> None:
        art = self.root / "g25"
        harness = art / "python_harness"
        harness.mkdir(parents=True)
        _qualifying_report(harness)
        time.sleep(1.1)
        proc = self._run(
            GATE25,
            self._env(
                art,
                "stale-pass",
                OPENFDD_SECURITY_EXECUTE="1",
                OPENFDD_API_BASE="http://127.0.0.1:18080",
                OPENFDD_SECURITY_PROFILE="live_readonly",
                OPENFDD_SECURITY_CONFIG=str(EXAMPLE),
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")
        self.assertIn("stale", verdict["reason"].lower())

    def test_gate25b_stale_pass_report_is_not_green(self) -> None:
        art = self.root / "g25b"
        harness = art / "python_harness_post"
        harness.mkdir(parents=True)
        _qualifying_report(harness)
        time.sleep(1.1)
        proc = self._run(
            GATE25B,
            self._env(
                art,
                "stale-pass",
                OPENFDD_SECURITY_EXECUTE="1",
                OPENFDD_API_BASE="http://127.0.0.1:18080",
                OPENFDD_SECURITY_PROFILE="live_readonly",
                OPENFDD_SECURITY_CONFIG=str(EXAMPLE),
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")
        self.assertIn("stale", verdict["reason"].lower())

    def test_gate25_transport_error_is_not_blocked(self) -> None:
        art = self.root / "g25e"
        template = self.root / "error-report.json"
        _error_report(template)
        proc = self._run(
            GATE25,
            self._env(
                art,
                "copy-template",
                OPENFDD_SECURITY_EXECUTE="1",
                OPENFDD_API_BASE="http://127.0.0.1:18080",
                OPENFDD_SECURITY_PROFILE="live_readonly",
                OPENFDD_SECURITY_CONFIG=str(EXAMPLE),
                OPENFDD_SABOTAGE_TEMPLATE=str(template),
                OPENFDD_SABOTAGE_RC="2",
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertFalse(verdict["ok"])

    def test_gate25b_transport_error_is_not_blocked(self) -> None:
        art = self.root / "g25be"
        template = self.root / "error-report.json"
        _error_report(template)
        proc = self._run(
            GATE25B,
            self._env(
                art,
                "copy-template",
                OPENFDD_SECURITY_EXECUTE="1",
                OPENFDD_API_BASE="http://127.0.0.1:18080",
                OPENFDD_SECURITY_PROFILE="live_readonly",
                OPENFDD_SECURITY_CONFIG=str(EXAMPLE),
                OPENFDD_SABOTAGE_TEMPLATE=str(template),
                OPENFDD_SABOTAGE_RC="2",
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertFalse(verdict["ok"])

    def test_gate25_pass_report_with_failed_child_is_not_green(self) -> None:
        art = self.root / "g25rc"
        template_dir = self.root / "pass-template"
        template_dir.mkdir()
        _qualifying_report(template_dir)
        proc = self._run(
            GATE25,
            self._env(
                art,
                "copy-template",
                OPENFDD_SECURITY_EXECUTE="1",
                OPENFDD_API_BASE="http://127.0.0.1:18080",
                OPENFDD_SECURITY_PROFILE="live_readonly",
                OPENFDD_SECURITY_CONFIG=str(EXAMPLE),
                OPENFDD_SABOTAGE_TEMPLATE=str(template_dir / "security_report.json"),
                OPENFDD_SABOTAGE_RC="5",
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertEqual(verdict["status"], "ERROR")
        self.assertFalse(verdict["ok"])

    def test_gate26_fail_observer_exit_zero_is_not_green(self) -> None:
        art = self.root / "g26fail"
        template = self.root / "observer-fail.json"
        template.write_text(
            json.dumps(
                {
                    "ok": False,
                    "status": "FAIL",
                    "image": "ghcr.io/bbartling/openfdd-mqtt:sha-test",
                    "acl_source": "generated",
                    "reason": "observer failed closed",
                }
            ),
            encoding="utf-8",
        )
        proc = self._run(
            GATE26,
            self._env(
                art,
                "observer-fail-rc0",
                OPENFDD_MQTT_ACL_EXECUTE="1",
                OPENFDD_SABOTAGE_TEMPLATE=str(template),
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")

    def test_gate26_ok_false_status_pass_is_not_green(self) -> None:
        art = self.root / "g26flip"
        template = self.root / "observer-flip.json"
        template.write_text(
            json.dumps(
                {
                    "ok": False,
                    "status": "PASS",
                    "image": "ghcr.io/bbartling/openfdd-mqtt:sha-test",
                    "acl_source": "generated",
                    "reason": "contradictory observer",
                }
            ),
            encoding="utf-8",
        )
        proc = self._run(
            GATE26,
            self._env(
                art,
                "observer-contradict",
                OPENFDD_MQTT_ACL_EXECUTE="1",
                OPENFDD_SABOTAGE_TEMPLATE=str(template),
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "ERROR")

    def test_gate26_stale_pass_observer_is_not_green(self) -> None:
        art = self.root / "g26stale"
        obs = art / "observer"
        obs.mkdir(parents=True)
        payload = {
            "ok": True,
            "status": "PASS",
            "image": "ghcr.io/bbartling/openfdd-mqtt:sha-test",
            "acl_source": "generated",
            "reason": "stale pass",
        }
        (obs / "mqtt_acl_observer.json").write_text(json.dumps(payload), encoding="utf-8")
        time.sleep(1.1)
        proc = self._run(
            GATE26,
            self._env(
                art,
                "stale-pass",
                OPENFDD_MQTT_ACL_EXECUTE="1",
            ),
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        verdict = self._verdict(art)
        self.assertFalse(verdict["ok"])
        self.assertNotEqual(verdict["status"], "PASS")
        self.assertIn("stale", verdict["reason"].lower())

    def test_record_status_refuses_pass_when_child_failed(self) -> None:
        proc = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; security_gate_record_status 7 PASS ""',
                "bash",
                str(LIB),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ERROR")

    def test_record_status_refuses_blocked_when_a_check_is_error(self) -> None:
        report = self.root / "child-error.json"
        report.write_text(
            json.dumps(
                {"checks": [{"check_id": "y.authz.a_own_building_control", "status": "ERROR"}]}
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; security_gate_record_status 2 BLOCKED "$2"',
                "bash",
                str(LIB),
                str(report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ERROR")


if __name__ == "__main__":
    unittest.main()
