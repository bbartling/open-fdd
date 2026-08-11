"""Classifier for intentional 4.3.0 WattLab deltas."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wattlab_parity_diff import (  # noqa: E402
    _intentional_43,
    _sql_screening_pair,
    _status_ok,
)


def test_chw1_skip_vs_zero_fault_is_accepted():
    ok, why = _intentional_43("CHW-1", "SKIPPED_EQUIPMENT_OFF", "FAULT", 0.0, 0.0)
    assert ok
    assert "CHW-1" in why


def test_sched247_pressure_fault_is_accepted():
    ok, why = _intentional_43("SCHED-247", "PASS", "FAULT", 0.0, 1561.0)
    assert ok
    assert "SCHED-247" in why


def test_other_rule_status_mismatch_not_intentional():
    ok, _ = _intentional_43("FC1", "PASS", "FAULT", 0.0, 12.0)
    assert not ok


def test_sql_screening_na_and_skip():
    ok, _ = _sql_screening_pair("AHU-DUCTHI", "NOT_APPLICABLE_EQUIPMENT_TYPE", "PASS", 0.0, 0.0)
    assert ok
    ok, _ = _sql_screening_pair("VAV-1", "SKIPPED_EQUIPMENT_OFF", "FAULT", 0.0, 12.0)
    assert ok


def test_pass_aliases():
    assert _status_ok("PASS", "OK")
    assert _status_ok("SKIPPED_MISSING_ROLES", "SKIPPED_EQUIPMENT_OFF")
    assert not _status_ok("PASS", "FAULT")
