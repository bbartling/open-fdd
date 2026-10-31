"""LPS_PER_CFM contract law for ip_unit cfm registry/tuning controls (#1284 / FC6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    METRIC_UNITS,
    REGISTRY,
    REJECTED_LPS_PER_CFM,
    TUNING,
    assert_ip_unit_cfm_si_values,
    iter_ip_unit_cfm_params,
    lps_per_cfm_contract,
    load_json,
    param_satisfies_ip_unit_cfm_contract,
)

from open_fdd.units.convert import LPS_PER_CFM  # noqa: E402


def test_lps_per_cfm_matches_metric_contract() -> None:
    metric = load_json(METRIC_UNITS)
    assert LPS_PER_CFM == lps_per_cfm_contract(metric) == 0.471947


def test_rejected_lps_factor_is_not_the_contract() -> None:
    assert REJECTED_LPS_PER_CFM != LPS_PER_CFM
    assert 5000.0 * REJECTED_LPS_PER_CFM != 5000.0 * LPS_PER_CFM


def test_fc6_min_cfm_design_matches_5000_cfm_contract() -> None:
    metric = load_json(METRIC_UNITS)
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    fc6 = next(r for r in registry["rules"] if r["rule_id"] == "FC6")
    param = fc6["parameters"]["min_cfm_design"]
    assert_ip_unit_cfm_si_values(metric, "FC6.min_cfm_design", param)
    assert param["default"] == pytest.approx(5000.0 * LPS_PER_CFM, rel=1e-9)
    assert param["max"] == pytest.approx(200_000.0 * LPS_PER_CFM, rel=1e-9)
    assert param["step"] == pytest.approx(100.0 * LPS_PER_CFM, rel=1e-9)


def test_mutation_wrong_factor_values_fail_contract() -> None:
    metric = load_json(METRIC_UNITS)
    bad = {
        "unit": "L_per_s",
        "ip_unit": "cfm",
        "default": 5000.0 * REJECTED_LPS_PER_CFM,
        "min": 0.0,
        "max": 200_000.0 * REJECTED_LPS_PER_CFM,
        "step": 100.0 * REJECTED_LPS_PER_CFM,
    }
    assert not param_satisfies_ip_unit_cfm_contract(metric, bad)
    with pytest.raises(AssertionError, match="round\\(cfm\\)×LPS_PER_CFM"):
        assert_ip_unit_cfm_si_values(metric, "mutation", bad)


def test_tuning_catalog_ip_unit_cfm_controls_match_contract() -> None:
    metric = load_json(METRIC_UNITS)
    tuning = json.loads(TUNING.read_text(encoding="utf-8"))
    for rule_id, key, param in iter_ip_unit_cfm_params(tuning, "tuning"):
        assert_ip_unit_cfm_si_values(metric, f"{rule_id}.{key}", param)


def test_check_unit_contract_includes_lps_law() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/ci/check_unit_contract.py"],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "PASS ip_unit cfm L/s parameters match LPS_PER_CFM" in proc.stdout
