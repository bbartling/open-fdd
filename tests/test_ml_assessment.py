"""Assessed vs unassessed rows for PCA and gray-box (#1666 acceptance 1 and 6)."""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

from open_fdd.ml.detectors import GreyBox, PCASPE  # noqa: E402


def _ahu(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    oat = 10 + 12 * np.sin(np.arange(n) / 288 * 2 * np.pi) + rng.normal(0, 0.3, n)
    return_air_temperature = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    mixed_air_temperature = damper * oat + (1 - damper) * return_air_temperature + rng.normal(0, 0.1, n)
    valve = np.clip((mixed_air_temperature - 13) / 10, 0, 1)
    discharge_air_temperature = mixed_air_temperature - 10 * valve + rng.normal(0, 0.1, n)
    return pd.DataFrame({"discharge_air_temperature": discharge_air_temperature, "discharge_air_temperature_setpoint": 13.0, "mixed_air_temperature": mixed_air_temperature,
                         "return_air_temperature": return_air_temperature, "outdoor_air_intake_temperature": oat, "outdoor_air_intake_damper_position_command": damper,
                         "cooling_valve_position_command": valve, "supply_fan_operating_status": 1.0}, index=idx)


def test_issue_repro_greybox_without_its_inputs_is_unassessed_not_healthy():
    """The #1666 repro: 100 active rows, every trained residual input removed -> 100 NaN scores, 0 flags."""
    gb = GreyBox().fit(_ahu())
    bare = _ahu(100, seed=1).drop(columns=["mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_damper_position_command",
                                           "cooling_valve_position_command", "discharge_air_temperature_setpoint"])
    assert gb.scores(bare).isna().all() and not gb.flags(bare).any()  # what a caller used to read as "no fault"
    a = gb.assessment(bare)
    assert (a == "missing_inputs").all() and not gb.assessed_mask(bare).any()
    assert set(gb.missing_residuals(bare)) == set(gb.tables_)


def test_greybox_assessed_inactive_and_no_residual():
    gb = GreyBox().fit(_ahu())
    f = _ahu(200, seed=2)
    f.iloc[:20, f.columns.get_loc("supply_fan_operating_status")] = 0.0
    f.iloc[20:40, [f.columns.get_loc(c) for c in ("mixed_air_temperature", "discharge_air_temperature")]] = np.nan
    a = gb.assessment(f)
    assert (a.iloc[:20] == "inactive").all()
    assert (a.iloc[20:40] == "no_residual").all()  # inputs exist in the frame, NaN on these rows
    assert (a.iloc[40:] == "assessed").mean() > 0.9
    assert not (gb.flags(f) & ~gb.assessed_mask(f)).any()  # a flag is only ever on an assessed row
    assert gb.missing_residuals(f) == []


def test_pca_assessment_and_missing_roles():
    pca = PCASPE().fit(_ahu())
    f = _ahu(120, seed=3)
    f.iloc[:10, f.columns.get_loc("supply_fan_operating_status")] = 0.0
    f.iloc[10:30, f.columns.get_loc("mixed_air_temperature")] = np.nan
    a = pca.assessment(f)
    assert (a.iloc[:10] == "inactive").all() and (a.iloc[10:30] == "missing_inputs").all()
    assert (a.iloc[30:] == "assessed").all()
    assert pca.missing_roles(f.drop(columns=["mixed_air_temperature"])) == ["mixed_air_temperature"]
    assert (pca.assessment(f.drop(columns=["mixed_air_temperature"])).iloc[10:] == "missing_inputs").all()


def test_unfitted_models_refuse_to_assess():
    with pytest.raises(RuntimeError, match="not fitted"):
        PCASPE().assessment(_ahu(20))
    with pytest.raises(RuntimeError, match="not fitted"):
        GreyBox().assessment(_ahu(20))
