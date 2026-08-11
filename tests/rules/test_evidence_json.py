"""Evidence JSON must never contain a pandas repr."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from open_fdd.rules.base import RuleResult
from open_fdd.rules.evidence import UnsafeEvidenceError, assert_no_pandas_repr, json_safe


def test_json_safe_summarizes_series_without_ellipsis():
    idx = pd.date_range("2026-01-01", periods=80, freq="5min", tz="UTC")
    s = pd.Series(np.linspace(70, 78, 80), index=idx, name="zone-air-temp")
    blob = json.dumps(json_safe(s), sort_keys=True)
    assert_no_pandas_repr(blob)
    parsed = json.loads(blob)
    assert parsed["role"] == "zone-air-temp"
    assert parsed["count"] == 80
    assert parsed["min"] == pytest.approx(70.0)
    assert parsed["max"] == pytest.approx(78.0)


def test_rule_result_to_dict_rejects_pandas_objects():
    idx = pd.date_range("2026-01-01", periods=40, freq="5min", tz="UTC")
    fault = pd.Series([False] * 20 + [True] * 20, index=idx)
    result = RuleResult(
        rule_id="FC1",
        equipment_id="AHU_1",
        status="FAULT",
        applicable=True,
        metrics={
            "gate_source": "fan-status",
            "quality_confidence": 0.9,
            "sv_sweep_confirmed_roles": {"oa_t": fault.astype(int)},
        },
        confirmed_fault=fault,
    )
    blob = json.dumps(result.to_dict(), sort_keys=True)
    assert_no_pandas_repr(blob)
    assert "dtype:" not in blob
    parsed = json.loads(blob)
    assert parsed["evidence"]["gate_source"] == "fan-status"
    assert parsed["metrics"]["sv_sweep_confirmed_roles"]["oa_t"]["count"] >= 1


def test_json_safe_rejects_unknown_objects():
    class Blob:
        pass

    with pytest.raises(UnsafeEvidenceError):
        json_safe(Blob())
