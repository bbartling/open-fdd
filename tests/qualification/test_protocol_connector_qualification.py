"""Fail-closed tests for Phase 5D protocol connector evidence."""

from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "qualification"))

import protocol_connector_qualification as qualification  # noqa: E402


def now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def complete_haystack() -> dict:
    observed = now()
    checks = []
    for check_id in qualification.REQUIRED_CHECKS["haystack_live"]:
        evidence = {"observed_at": observed}
        if check_id == "trusted_catalog":
            evidence.update(
                catalog_fingerprint="sha256:catalog",
                trusted_source=True,
                catalog_records=2,
            )
        if check_id == "authenticated_basic_or_scram":
            evidence.update(
                auth_mode="basic",
                auth_ok=True,
                credentials_source="secure_local_config",
            )
        if check_id in {"about_read", "nav_read", "current_read"}:
            evidence.update(request_count=1, status_code=200, read_ok=True)
        if check_id == "history_read":
            evidence.update(request_count=1, status_code=200, read_ok=True, sample_count=1)
        if check_id == "typed_timestamps_units":
            evidence.update(typed_timestamps=True, units_present=True)
        if check_id == "central_receipt_committed":
            receipt = {
                "message_id": "request-1",
                "scope": "tenant=tenant;building=building",
                "site_id": "site",
                "edge_id": "edge",
                "status": "committed",
                "eligible_points": 1,
                "persisted_rows": 1,
            }
            evidence.update(receipt=receipt, expected_receipt=copy.deepcopy(receipt))
        if check_id == "historian_readback":
            evidence.update(
                sample_count=1,
                expected_sample_count=1,
                historian_readback_ok=True,
            )
        if check_id == "replay_no_duplicate":
            evidence.update(replay_count=1, duplicate_rows=0, conflict_rejected=True)
        if check_id == "restart_resume":
            evidence.update(restarted=True, resumed=True, pending_recovered=True)
        if check_id == "no_udp_or_bacnet_routes":
            evidence.update(udp_socket_count=0, bacnet_route_count=0)
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS",
                "detail": "redacted test evidence",
                "evidence": evidence,
            }
        )
    return {"observed_at": observed, "checks": checks}


def complete_bacnet() -> dict:
    observed = now()
    evidence_by_check = {
        "device_reachable": {"device_instance": 5007, "reachable": True},
        "read_only": {
            "operation_mode": "read_only",
            "write_property_count": 0,
            "release_count": 0,
        },
        "typed_point_tree": {"point_count": 2, "typed": True},
        "present_value_refresh": {"refreshed_points": 2, "typed_values": True},
        "priority_array_read": {"priority_array_reads": 1},
        "priority_history_visit": {
            "priority_history_visits": 1,
            "non_overlapping": True,
        },
        "restart_recovery": {
            "restarted": True,
            "recovered": True,
            "history_persisted": True,
        },
        "no_write_release": {"write_property_count": 0, "release_count": 0},
        "bounded_workload": {
            "request_count": 4,
            "duration_seconds": 2,
            "max_duration_seconds": 10,
            "max_request_count": 20,
        },
    }
    return {
        "observed_at": observed,
        "checks": [
            {
                "check_id": check_id,
                "status": "PASS",
                "detail": "redacted test evidence",
                "evidence": {"observed_at": observed, **evidence_by_check[check_id]},
            }
            for check_id in qualification.REQUIRED_CHECKS["bacnet_live"]
        ],
    }


class ProtocolConnectorQualificationTests(unittest.TestCase):
    def test_synthetic_stage_passes_only_requested_contract(self) -> None:
        stage = qualification.validate_stage("synthetic", qualification.synthetic_stage())
        self.assertEqual(stage["status"], "PASS")
        report = {"schema_version": qualification.SCHEMA_VERSION, "stages": {"synthetic": stage}}
        accepted, _ = qualification.evaluate_report(report, ("synthetic",))
        self.assertTrue(accepted)
        accepted, _ = qualification.evaluate_report(report, qualification.STAGES)
        self.assertFalse(accepted, "missing live/image stages must never qualify")

    def test_empty_partial_stale_and_forged_evidence_are_blocked(self) -> None:
        good = qualification.synthetic_stage()
        cases = [
            {},
            {"checks": good["checks"][:1], "observed_at": good["observed_at"]},
            {**good, "observed_at": "2020-01-01T00:00:00Z"},
        ]
        for raw in cases:
            stage = qualification.validate_stage("synthetic", raw)
            self.assertNotEqual(stage["status"], "PASS")
        forged = {
            "schema_version": qualification.SCHEMA_VERSION,
            "overall_status": "PASS",
            "fully_qualified": True,
            "stages": {},
        }
        accepted, _ = qualification.evaluate_report(forged, ("synthetic",))
        self.assertFalse(accepted)

    def test_contradictory_status_cannot_override_a_failed_check(self) -> None:
        raw = qualification.synthetic_stage()
        raw["checks"][0]["status"] = "FAIL"
        normalized = qualification.validate_stage("synthetic", raw)
        self.assertEqual(normalized["status"], "FAIL")
        self.assertFalse(
            qualification.evaluate_report(
                {"schema_version": qualification.SCHEMA_VERSION, "stages": {"synthetic": normalized}},
                ("synthetic",),
            )[0]
        )

    def test_live_pass_requires_check_specific_proof(self) -> None:
        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "nav_read":
                check["evidence"].pop("request_count")
        normalized = qualification.validate_stage("haystack_live", raw)
        self.assertEqual(normalized["status"], "BLOCKED")

        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "replay_no_duplicate":
                check["evidence"]["duplicate_rows"] = 1
        normalized = qualification.validate_stage("haystack_live", raw)
        self.assertEqual(normalized["status"], "FAIL")

    def test_receipt_and_historian_mismatches_fail_closed(self) -> None:
        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "central_receipt_committed":
                check["evidence"]["expected_receipt"]["message_id"] = "different"
        normalized = qualification.validate_stage("haystack_live", raw)
        self.assertEqual(normalized["status"], "FAIL")

        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "historian_readback":
                check["evidence"]["expected_sample_count"] = 2
        normalized = qualification.validate_stage("haystack_live", raw)
        self.assertEqual(normalized["status"], "FAIL")

    def test_prohibited_surface_and_bacnet_write_evidence_fail(self) -> None:
        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "no_udp_or_bacnet_routes":
                check["evidence"]["udp_socket_count"] = 1
        self.assertEqual(qualification.validate_stage("haystack_live", raw)["status"], "FAIL")

        raw = complete_bacnet()
        for check in raw["checks"]:
            if check["check_id"] == "no_write_release":
                check["evidence"].update(write_property_count=1, release_count=0)
        self.assertEqual(qualification.validate_stage("bacnet_live", raw)["status"], "FAIL")

    def test_missing_command_auth_owner_and_historian_fail_closed(self) -> None:
        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "about_read":
                check["evidence"]["missing_commands"] = ["curl"]
        self.assertNotEqual(qualification.validate_stage("haystack_live", raw)["status"], "PASS")

        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "authenticated_basic_or_scram":
                check["evidence"]["auth_ok"] = False
        self.assertEqual(qualification.validate_stage("haystack_live", raw)["status"], "FAIL")

        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "no_udp_or_bacnet_routes":
                check["evidence"]["listener_owner_ok"] = False
        self.assertEqual(qualification.validate_stage("haystack_live", raw)["status"], "FAIL")

        raw = complete_haystack()
        for check in raw["checks"]:
            if check["check_id"] == "historian_readback":
                check["evidence"]["historian_readback_ok"] = False
        self.assertEqual(qualification.validate_stage("haystack_live", raw)["status"], "FAIL")

    def test_secret_text_is_redacted_and_bounded(self) -> None:
        detail = qualification.sanitize_text(
            "Authorization: Bearer super-secret-token password=hunter2 https://user:pass@example.invalid "
            + "x" * 1000
        )
        self.assertNotIn("super-secret-token", detail)
        self.assertNotIn("hunter2", detail)
        self.assertNotIn("user:pass@", detail)
        self.assertLessEqual(len(detail), qualification.MAX_DETAIL_CHARS)


if __name__ == "__main__":
    unittest.main()
