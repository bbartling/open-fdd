"""Astra A09: profile-bound image digest / SBOM / provenance evaluator."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from profile_image_scan import (  # noqa: E402
    evaluate_scan_evidence,
    profile_required_scan_images,
    selftest,
)


class ProfileImageScanTest(unittest.TestCase):
    def test_selftest_pass(self) -> None:
        report = selftest()
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["status"], "PASS")

    def test_cloud_requires_mqtt_not_ot(self) -> None:
        names = profile_required_scan_images("cloud_mqtt_hub")
        self.assertIn("openfdd-mqtt", names)
        self.assertNotIn("openfdd-bacnet-modbus", names)
        self.assertNotIn("openfdd-haystack", names)

    def test_ot_bacnet_requires_connector_and_caddy(self) -> None:
        names = profile_required_scan_images("ot_local_bacnet_modbus")
        self.assertIn("openfdd-bacnet-modbus", names)
        self.assertIn("caddy", names)
        self.assertNotIn("openfdd-haystack", names)

    def test_workflow_inference_rejected(self) -> None:
        digest = "sha256:" + ("a" * 64)
        evidence = {
            "schema_version": "openfdd_profile_image_scan_v1",
            "profile_id": "cloud_mqtt_hub",
            "images": [
                {
                    "name": "openfdd-web",
                    "digest": digest,
                    "ref": f"ghcr.io/bbartling/openfdd-web@{digest}",
                    "platform": "linux/amd64",
                },
                {
                    "name": "openfdd-central",
                    "digest": "sha256:" + ("b" * 64),
                    "ref": "ghcr.io/bbartling/openfdd-central@sha256:" + ("b" * 64),
                    "platform": "linux/amd64",
                },
                {
                    "name": "openfdd-mqtt",
                    "digest": "sha256:" + ("c" * 64),
                    "ref": "ghcr.io/bbartling/openfdd-mqtt@sha256:" + ("c" * 64),
                    "platform": "linux/amd64",
                },
            ],
            "scanner": {"tool": "trivy", "version": "0.56.0"},
            "findings": {"critical": 0, "high": 0, "medium": 0},
            "sbom": {"status": "PRESENT", "artifact_digests": [digest]},
            "provenance": {
                "status": "VERIFIED",
                "method": "workflow_file_present",
                "attestation_digests": [digest],
            },
        }
        report = evaluate_scan_evidence("cloud_mqtt_hub", evidence)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            any(c["id"] == "provenance.not_workflow_inference" and not c["ok"] for c in report["checks"])
        )


if __name__ == "__main__":
    unittest.main()
