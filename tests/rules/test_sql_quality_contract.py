"""SQL ↔ pandas quality contract (#1253).

Warehouse / Timescale SQL is the product FDD path and does **not** apply
``open_fdd.quality`` OUT_OF_RANGE / sentinel nulling. The contractual pandas
oracle for SQL parity therefore runs with quality OFF (equation + gate +
confirm only). Full ``run_rule`` (quality ON) is a separate surface.

Fail-closed: when dirty setpoints would be nulled, quality-ON hours must be
strictly less than SQL-aligned quality-OFF hours — never silently equalized
by weakening either path.
"""

from __future__ import annotations

import pandas as pd

from open_fdd.quality import REASON_OUT_OF_RANGE, apply_normalized, assess_frame
from open_fdd.rules import RULES_BY_ID, run_rule
from open_fdd.rules.base import confirm_fault, hours_true
from open_fdd.rules.operational_gate import resolve_operational_mask

POLL_S = 300.0


def _satdev_frame(*, n: int = 24) -> pd.DataFrame:
    """Half-clean SAT fault + half OUT_OF_RANGE sat_sp (still equation-fault)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    half = n // 2
    df = pd.DataFrame(
        {
            "discharge-air-temp": [65.0] * n,
            # 55°F → |65−55|=10 > 5 (fault, in-range)
            # 200°F → OUT_OF_RANGE for discharge-air-temp family; still |65−200|>5
            "discharge-air-temp-sp": [55.0] * half + [200.0] * (n - half),
            "fan-status": [1.0] * n,
        },
        index=idx,
    )
    df.attrs.update(equipment_id="AHU_1", equipment_type="ahu", building_id="SYNTH_01")
    return df


def _sql_aligned_hours(df: pd.DataFrame, *, quality: bool) -> tuple[float, dict]:
    rule = RULES_BY_ID["AHU-SATDEV"]
    d = df
    qmeta: dict = {}
    if quality:
        fq = assess_frame(d, [c for c in d.columns])
        d = apply_normalized(d, fq, attach_raw_and_flags=False)
        qmeta = {
            "invalid_sample_count": fq.invalid_sample_count,
            "reason_counts": dict(fq.reason_counts),
        }
    params = {"confirm_min": 0.0, "startup_delay_min": 0.0}
    full = dict(rule.defaults())
    full.update(params)
    confirm_s = float(full.get("confirm_min", rule.confirm_seconds / 60.0)) * 60.0
    active, gate_meta = resolve_operational_mask(
        d, "AHU-SATDEV", poll_seconds=POLL_S, params=full, gate_enabled=True
    )
    raw = rule.compute(d, full, POLL_S).reindex(d.index).fillna(False).astype(bool)
    if gate_meta.get("gate_applied"):
        raw = raw & active.reindex(d.index).fillna(False).astype(bool)
    confirmed = confirm_fault(raw, poll_seconds=POLL_S, confirm_seconds=confirm_s)
    return float(hours_true(pd.Series(confirmed, index=d.index), POLL_S)), {
        "fault_samples": int(confirmed.sum()),
        "quality": qmeta,
        "gate_source": gate_meta.get("gate_source"),
    }


def test_ahu_satdev_quality_off_is_sql_contract_surface():
    """SQL-aligned oracle (quality OFF) keeps OUT_OF_RANGE samples as faults."""
    df = _satdev_frame()
    off_h, off_meta = _sql_aligned_hours(df, quality=False)
    on_h, on_meta = _sql_aligned_hours(df, quality=True)
    runner = run_rule(
        "AHU-SATDEV",
        df,
        params={"confirm_min": 0.0, "startup_delay_min": 0.0},
        poll_seconds=POLL_S,
        require_operational_gates=True,
    )

    assert off_meta["fault_samples"] == 24
    assert off_h == 2.0  # 24 × 300 s
    assert on_meta["quality"]["reason_counts"].get(REASON_OUT_OF_RANGE) == 12
    assert on_meta["fault_samples"] == 12
    assert on_h == 1.0
    # Fail-closed: quality ON must drop hours vs SQL-aligned OFF on dirty packs.
    assert on_h < off_h
    # Full runner matches quality-ON oracle (same surface).
    assert runner.status == "FAULT"
    assert float(runner.fault_hours) == on_h
    # Contract reminder: warehouse SQL twins OFF, not ON (#1253).
    assert off_h != on_h


def test_ahu_satdev_short_sql_aliases_are_not_pandas_columns():
    """Warehouse aliases (sat/sat_sp) must not silently green pandas parity."""
    idx = pd.date_range("2026-01-01", periods=6, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "sat": [65.0] * 6,
            "sat_sp": [55.0] * 6,
            "fan_status": [1.0] * 6,
        },
        index=idx,
    )
    df.attrs.update(equipment_id="AHU_1", equipment_type="ahu")
    result = run_rule(
        "AHU-SATDEV",
        df,
        params={"confirm_min": 0.0, "startup_delay_min": 0.0},
        poll_seconds=POLL_S,
        require_operational_gates=True,
    )
    assert result.status == "SKIPPED_MISSING_ROLES"
