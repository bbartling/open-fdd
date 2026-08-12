"""Classifier for intentional 4.3.0 WattLab deltas — dump-vs-dump stop rule."""

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


def test_fc7_concept_only_is_accepted():
    ok, why = _intentional_43("FC7", "SKIPPED_MISSING_ROLES", "PASS", 0.0, 0.0)
    assert ok
    assert "concept_only" in why


def test_other_rule_status_mismatch_not_intentional():
    ok, _ = _intentional_43("FC1", "PASS", "FAULT", 0.0, 12.0)
    assert not ok


def test_fault_intersection_hours_are_blockers():
    ok, _ = _sql_screening_pair("FC1", "FAULT", "FAULT", 10.0, 200.0)
    assert not ok
    ok, _ = _sql_screening_pair("AHU-SATDEV", "FAULT", "FAULT", 373.0, 1730.0)
    assert not ok


def test_na_vs_pass_is_blocker():
    ok, _ = _sql_screening_pair("AHU-DUCTHI", "NOT_APPLICABLE_EQUIPMENT_TYPE", "PASS", 0.0, 0.0)
    assert not ok


def test_skip_vs_fault_is_blocker():
    ok, _ = _sql_screening_pair("VAV-1", "SKIPPED_EQUIPMENT_OFF", "FAULT", 0.0, 12.0)
    assert not ok


def test_pass_aliases():
    assert _status_ok("PASS", "OK")
    assert _status_ok("SKIPPED_MISSING_ROLES", "SKIPPED_EQUIPMENT_OFF")
    assert not _status_ok("PASS", "FAULT")
