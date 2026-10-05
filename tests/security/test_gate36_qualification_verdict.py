"""Q-01: gate 36 must not exit 0 on BLOCKED/empty-own/5xx SPARQL evidence."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _finalize(checks: list[dict], *, smoke: bool = False) -> tuple[int, dict]:
    """Replay the gate-36 finalizer jq logic from 36_model_ecm_qualification.sh."""
    with tempfile.TemporaryDirectory(prefix="gate36-") as td:
        art = Path(td)
        (art / "checks.json").write_text(json.dumps(checks) + "\n", encoding="utf-8")
        script = r"""
set -euo pipefail
ART="$1"
SMOKE="$2"
QUALIFY=1
if [[ "$SMOKE" == "1" ]]; then QUALIFY=0; fi
FAILS="$(jq '[.[] | select(.status=="FAIL" or .status=="ERROR")] | length' "$ART/checks.json")"
BLOCKED="$(jq '[.[] | select(.status=="BLOCKED" or .status=="SKIPPED")] | length' "$ART/checks.json")"
NA_BARE="$(jq '[.[] | select(.status=="NOT_APPLICABLE" and ((.detail//"")|tostring|length)==0)] | length' "$ART/checks.json")"
PASS_N="$(jq '[.[] | select(.status=="PASS")] | length' "$ART/checks.json")"
if [[ "$FAILS" -gt 0 ]]; then
  jq -n --argjson c "$(cat "$ART/checks.json")" '{ok:false,status:"FAIL",checks:$c}' >"$ART/verdict.json"
  exit 1
fi
if [[ "$QUALIFY" -eq 1 && ( "$BLOCKED" -gt 0 || "$NA_BARE" -gt 0 ) ]]; then
  jq -n --argjson c "$(cat "$ART/checks.json")" '{ok:false,status:"BLOCKED",checks:$c}' >"$ART/verdict.json"
  exit 2
fi
if [[ "$PASS_N" -eq 0 ]]; then
  jq -n --argjson c "$(cat "$ART/checks.json")" '{ok:false,status:"FAIL",checks:$c}' >"$ART/verdict.json"
  exit 1
fi
jq -n --argjson c "$(cat "$ART/checks.json")" '{ok:true,status:"PASS",checks:$c}' >"$ART/verdict.json"
exit 0
"""
        proc = subprocess.run(
            ["bash", "-c", script, "_", str(art), "1" if smoke else "0"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        verdict = json.loads((art / "verdict.json").read_text(encoding="utf-8"))
        return proc.returncode, verdict


class Gate36QualificationVerdictTests(unittest.TestCase):
    def test_blocked_own_mapping_cannot_qualify(self) -> None:
        rc, verdict = _finalize(
            [
                {"check": "model.ecm.mapping_own", "status": "BLOCKED", "detail": "status=503"},
                {
                    "check": "model.ecm.sparql_catalog_available",
                    "status": "PASS",
                    "detail": "AVAILABLE",
                },
            ]
        )
        self.assertNotEqual(rc, 0)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "BLOCKED")

    def test_empty_own_inventory_fail_cannot_pass(self) -> None:
        rc, verdict = _finalize(
            [
                {
                    "check": "model.ecm.mapping_own",
                    "status": "FAIL",
                    "detail": "200 without nonempty owner inventory",
                },
                {"check": "model.ecm.sparql_freeform_rejected", "status": "PASS"},
            ]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["status"], "FAIL")

    def test_sparql_5xx_error_cannot_pass(self) -> None:
        rc, verdict = _finalize(
            [
                {
                    "check": "model.ecm.mapping_own",
                    "status": "PASS",
                    "detail": "200 nonempty",
                },
                {
                    "check": "model.ecm.sparql_unavailable",
                    "status": "ERROR",
                    "detail": "transport status=500",
                },
            ]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(verdict["ok"])

    def test_smoke_allows_blocked(self) -> None:
        rc, verdict = _finalize(
            [
                {"check": "model.ecm.mapping_own", "status": "BLOCKED", "detail": "503"},
                {"check": "model.ecm.sparql_catalog_available", "status": "PASS"},
            ],
            smoke=True,
        )
        self.assertEqual(rc, 0)
        self.assertTrue(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
