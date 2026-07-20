"""Shared rule helpers and standard result contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.runtime_intervals import UNLIMITED_GAP_SECONDS, interval_durations

RuleStatus = Literal[
    "PASS",
    "FAULT",
    "SKIPPED_MISSING_ROLES",
    "SKIPPED_EQUIPMENT_OFF",
    "NOT_APPLICABLE_EQUIPMENT_TYPE",
    "ERROR",
]


def _sample_deltas_seconds(index: pd.Index, poll_seconds: float) -> pd.Series | None:
    """Per-sample duration (seconds) until the next timestamp; last uses median/poll."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return None
    if len(index) == 1:
        return pd.Series([float(poll_seconds)], index=index)
    durations = interval_durations(
        index,
        nominal_seconds=poll_seconds,
        max_gap_seconds=UNLIMITED_GAP_SECONDS,
        final_duration_seconds=0.0,
        preserve_row_order=True,
    )
    med = (
        float(durations.iloc[:-1].median())
        if len(durations) > 1 and durations.iloc[:-1].notna().any()
        else float(poll_seconds)
    )
    if not np.isfinite(med) or med < 0:
        med = float(max(poll_seconds, 0.0))
    durations = durations.copy()
    durations.iloc[-1] = med
    return durations


def confirm_fault(raw: pd.Series, *, poll_seconds: float, confirm_seconds: float = 300.0) -> pd.Series:
    """Require the raw fault to persist for ``confirm_seconds`` before confirming.

    When the series has a DatetimeIndex, accumulate actual sample gaps within each
    True run. Otherwise fall back to row-count math using ``poll_seconds``.
    """
    raw = raw.fillna(False).astype(bool)
    if confirm_seconds <= 0:
        return raw

    deltas = _sample_deltas_seconds(raw.index, poll_seconds)
    if deltas is not None:
        groups = (raw != raw.shift()).cumsum()
        contrib = deltas.where(raw, 0.0)
        cum = contrib.groupby(groups).cumsum()
        return raw & (cum >= float(confirm_seconds))

    rows = max(1, int(np.ceil(confirm_seconds / max(poll_seconds, 1))))
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= rows)


def hours_true(mask: pd.Series, poll_seconds: float) -> float:
    """Hours under a boolean mask using actual timestamp deltas when available."""
    m = mask.fillna(False).astype(bool)
    deltas = _sample_deltas_seconds(m.index, poll_seconds)
    if deltas is not None:
        return float((m.astype(float) * (deltas / 3600.0)).sum())
    return float(m.sum()) * poll_seconds / 3600.0


def params_fingerprint(rule_id: str, params: dict[str, Any], *, gates_on: bool) -> str:
    """Stable short hash of the resolved param dict used for a run."""
    payload = {"rule_id": rule_id, "params": params, "gates": bool(gates_on)}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


@dataclass
class RuleResult:
    rule_id: str
    equipment_id: str
    status: RuleStatus
    applicable: bool
    site_id: str = ""
    building_id: str = ""
    equipment_type: str = "UNKNOWN"
    missing_roles: list[str] = field(default_factory=list)
    fault_hours: float | None = None
    fault_pct: float | None = None
    sample_count: int = 0
    fault_sample_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    debug: pd.DataFrame | None = None
    notes: str = ""
    raw_fault: pd.Series | None = None
    confirmed_fault: pd.Series | None = None
    plot_series: dict[str, pd.Series] = field(default_factory=dict)
    params_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "equipment_id": self.equipment_id,
            "site_id": self.site_id,
            "building_id": self.building_id,
            "equipment_type": self.equipment_type,
            "status": self.status,
            "applicable": self.applicable,
            "missing_roles": list(self.missing_roles),
            "fault_hours": self.fault_hours,
            "fault_pct": self.fault_pct,
            "sample_count": self.sample_count,
            "fault_sample_count": self.fault_sample_count,
            "metrics": dict(self.metrics),
            "debug": self.debug,
            "notes": self.notes,
            "params_fingerprint": self.params_fingerprint,
        }


def skipped(
    rule_id: str,
    equipment_id: str,
    missing: list[str],
    notes: str = "",
    *,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "UNKNOWN",
    params_fingerprint: str = "",
) -> RuleResult:
    msg = f"SKIPPED — missing roles: {', '.join(missing)}"
    return RuleResult(
        rule_id=rule_id,
        equipment_id=equipment_id,
        site_id=site_id,
        building_id=building_id,
        equipment_type=equipment_type,
        status="SKIPPED_MISSING_ROLES",
        applicable=False,
        missing_roles=missing,
        fault_hours=None,
        fault_pct=None,
        notes=notes or msg,
        params_fingerprint=params_fingerprint,
    )


def not_applicable(
    rule_id: str,
    equipment_id: str,
    equipment_kind: str,
    *,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "UNKNOWN",
    params_fingerprint: str = "",
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        equipment_id=equipment_id,
        site_id=site_id,
        building_id=building_id,
        equipment_type=equipment_type,
        status="NOT_APPLICABLE_EQUIPMENT_TYPE",
        applicable=False,
        missing_roles=[],
        notes=f"NOT_APPLICABLE — rule not applicable to equipment kind '{equipment_kind}'",
        params_fingerprint=params_fingerprint,
    )


def error_result(
    rule_id: str,
    equipment_id: str,
    exc: Exception,
    *,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "UNKNOWN",
    params_fingerprint: str = "",
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        equipment_id=equipment_id,
        site_id=site_id,
        building_id=building_id,
        equipment_type=equipment_type,
        status="ERROR",
        applicable=False,
        notes=f"ERROR — {type(exc).__name__}: {exc}",
        params_fingerprint=params_fingerprint,
    )


def equipment_off(
    rule_id: str,
    equipment_id: str,
    *,
    notes: str = "",
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "UNKNOWN",
    metrics: dict[str, Any] | None = None,
    params_fingerprint: str = "",
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        equipment_id=equipment_id,
        site_id=site_id,
        building_id=building_id,
        equipment_type=equipment_type,
        status="SKIPPED_EQUIPMENT_OFF",
        applicable=False,
        fault_hours=None,
        fault_pct=None,
        metrics=metrics or {},
        notes=notes
        or "SKIPPED_EQUIPMENT_OFF — equipment was not proven on during the analysis period.",
        params_fingerprint=params_fingerprint,
    )


def finalize_result(
    rule_id: str,
    equipment_id: str,
    raw: pd.Series,
    poll_seconds: float,
    confirm_seconds: float,
    *,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "UNKNOWN",
    metrics: dict[str, Any] | None = None,
    plot_series: dict[str, pd.Series] | None = None,
    active_mask: pd.Series | None = None,
    params_fingerprint: str = "",
) -> RuleResult:
    raw = raw.fillna(False).astype(bool)
    if active_mask is not None:
        active = active_mask.reindex(raw.index).fillna(False).astype(bool)
        raw = raw & active
    else:
        active = pd.Series(True, index=raw.index)

    confirmed = confirm_fault(raw, poll_seconds=poll_seconds, confirm_seconds=confirm_seconds)
    n_total = len(raw)
    n_active = int(active.sum())
    fault_n = int(confirmed.sum())
    active_h = hours_true(active, poll_seconds)
    fault_h = hours_true(confirmed, poll_seconds)
    pct = 100.0 * fault_h / active_h if active_h else 0.0
    status: RuleStatus = "FAULT" if fault_n > 0 else "PASS"
    metrics_out = dict(metrics or {})
    metrics_out.setdefault("active_sample_count", n_active)
    metrics_out.setdefault("total_sample_count", n_total)
    return RuleResult(
        rule_id=rule_id,
        equipment_id=equipment_id,
        site_id=site_id,
        building_id=building_id,
        equipment_type=equipment_type,
        status=status,
        applicable=True,
        fault_hours=round(fault_h, 2),
        fault_pct=round(pct, 2),
        sample_count=n_active if active_mask is not None else n_total,
        fault_sample_count=fault_n,
        metrics=metrics_out,
        raw_fault=raw,
        confirmed_fault=confirmed,
        plot_series=plot_series or {},
        notes=f"{fault_h:.1f}h fault ({pct:.1f}% of active)" if fault_n else "No confirmed faults",
        params_fingerprint=params_fingerprint,
    )
