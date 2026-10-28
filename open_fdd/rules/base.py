"""Shared rule helpers and standard result contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from open_fdd.analytics.runtime_intervals import ELAPSED_MAX_GAP_SECONDS

RuleStatus = Literal[
    "PASS",
    "FAULT",
    "SKIPPED_MISSING_ROLES",
    "SKIPPED_EQUIPMENT_OFF",
    "NOT_APPLICABLE_EQUIPMENT_TYPE",
    "NOT_ASSESSED_NO_OCCUPANCY",
    "ERROR",
]


def _eligible_hold_seconds(index: pd.Index) -> pd.Series | None:
    """Forward seconds until the next timestamp.

    The last sample is 0. A gap longer than one hour is 0 (unknown), not a
    clipped hold and not a median fill. Duplicate timestamps contribute 0.
    """
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return None
    current = index.to_series()
    delta = current.shift(-1).sub(current).dt.total_seconds()
    held = delta.where((delta > 0.0) & (delta <= ELAPSED_MAX_GAP_SECONDS), 0.0)
    return held.fillna(0.0)


def confirm_fault(raw: pd.Series, *, poll_seconds: float, confirm_seconds: float = 300.0) -> pd.Series:
    """Require the raw fault to persist for ``confirm_seconds`` of eligible time.

    Eligible time is the forward delta when it is positive and at most one hour.
    A longer gap is unknown: it is not fault time and it starts a new streak.
    The last sample has no forward interval. A non-datetime index falls back to
    row counts using ``poll_seconds``.
    """
    raw = raw.fillna(False).astype(bool)
    if confirm_seconds <= 0:
        return raw

    held = _eligible_hold_seconds(raw.index)
    if held is not None:
        current = raw.index.to_series()
        delta = current.shift(-1).sub(current).dt.total_seconds()
        gap_after = (delta > ELAPSED_MAX_GAP_SECONDS).fillna(False)
        prev_gap = gap_after.shift(1, fill_value=False).astype(bool)
        new_streak = raw.ne(raw.shift()) | prev_gap
        groups = new_streak.cumsum()
        contrib = held.where(raw, 0.0)
        cum = contrib.groupby(groups).cumsum()
        return raw & (cum >= float(confirm_seconds))

    rows = max(1, int(np.ceil(confirm_seconds / max(poll_seconds, 1))))
    groups = (raw != raw.shift()).cumsum()
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= rows)


def hours_true(mask: pd.Series, poll_seconds: float) -> float:
    """Hours under a boolean mask.

    A datetime index sums eligible forward holds. The last sample adds nothing,
    and a gap longer than one hour adds nothing. A non-datetime index uses
    ``poll_seconds`` per true row.
    """
    m = mask.fillna(False).astype(bool)
    held = _eligible_hold_seconds(m.index)
    if held is not None:
        return float((m.astype(float) * (held / 3600.0)).sum())
    return float(m.sum()) * poll_seconds / 3600.0


def params_fingerprint(rule_id: str, params: dict[str, Any], *, gates_on: bool) -> str:
    """Stable short hash of the resolved param dict used for a run."""
    from open_fdd.rules.evidence import json_safe

    payload = {"rule_id": rule_id, "params": json_safe(params), "gates": bool(gates_on)}
    blob = json.dumps(payload, sort_keys=True)
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
        from open_fdd.rules.evidence import json_safe, series_summary, sparse_intervals

        evidence = {
            "gate_source": (self.metrics or {}).get("gate_source"),
            "proof_quality": (self.metrics or {}).get("quality_confidence"),
            "confirmed_fault": None,
        }
        if self.confirmed_fault is not None:
            evidence["confirmed_fault"] = {
                **series_summary(self.confirmed_fault.astype(float), role="confirmed_fault"),
                "fault_intervals": sparse_intervals(self.confirmed_fault),
            }
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
            "metrics": json_safe(self.metrics),
            "evidence": evidence,
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


def not_assessed_no_occupancy(
    rule_id: str,
    equipment_id: str,
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
        status="NOT_ASSESSED_NO_OCCUPANCY",
        applicable=False,
        fault_hours=0.0,
        fault_pct=None,
        notes=(
            "NOT_ASSESSED_NO_OCCUPANCY — comfort band requires modeled occ_mode "
            "or a site occupancy schedule."
        ),
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
