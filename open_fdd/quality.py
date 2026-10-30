"""Role-aware input quality normalization.

Preserves raw values. Returns normalized series plus structured flags.
Zeros and ones are valid for status/command; they are not global sentinels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

DEFAULT_SENTINELS = (999.0, 888.0, -999.0, 9999.0, -9999.0)

REASON_SENTINEL = "SENTINEL"
REASON_NULL = "NULL"
REASON_NON_NUMERIC = "NON_NUMERIC"
REASON_OUT_OF_RANGE = "OUT_OF_RANGE"
REASON_IMPOSSIBLE = "IMPOSSIBLE_FOR_ROLE"

# Role family → (lo, hi) in native units after 0–1 vs 0–100 scaling for positions.
# None bound means “do not apply that side”.
ROLE_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "zone-air-temp": (40.0, 100.0),
    "zone-temp": (40.0, 100.0),
    "discharge-air-temp": (35.0, 140.0),
    "supply-air-temp": (35.0, 140.0),
    "mixed-air-temp": (20.0, 130.0),
    "return-air-temp": (40.0, 110.0),
    "outside-air-temp": (-40.0, 130.0),
    "chilled-water-supply-temp": (32.0, 80.0),
    "chilled-water-return-temp": (32.0, 90.0),
    "hot-water-supply-temp": (60.0, 220.0),
    "hot-water-return-temp": (50.0, 210.0),
    "zone-airflow": (0.0, 20000.0),
    "supply-airflow": (0.0, 100000.0),
    "airflow": (0.0, 100000.0),
    "duct-static-pressure": (-2.0, 6.0),
    "chw-diff-pressure": (0.0, 50.0),
    "chw-flow": (0.0, 20000.0),
    "water-flow": (0.0, 20000.0),
    "cooling-valve": (0.0, 100.0),
    "heating-valve": (0.0, 100.0),
    "economizer-damper": (0.0, 100.0),
    "oa-damper": (0.0, 100.0),
    "damper": (0.0, 100.0),
    "valve": (0.0, 100.0),
    "fan-power": (0.0, 500.0),
    "chiller-power": (0.0, 5000.0),
    "pump-power": (0.0, 500.0),
    "elec-power": (0.0, 50000.0),
    "fan-current": (0.0, 500.0),
    "chiller-current": (0.0, 2000.0),
    "pump-current": (0.0, 500.0),
    "fan-speed-feedback": (0.0, 100.0),
    "pump-speed-feedback": (0.0, 100.0),
}

STATUS_ROLES = {
    "fan-status",
    "pump-status",
    "chw-pump-status",
    "hw-pump-status",
    "chiller-status",
    "compressor-status",
    "occupied",
    "occ-mode",
    "equipment-enable",
    "loop-enabled",
}
COMMAND_ROLES = {
    "fan-cmd",
    "pump-cmd",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "tower-fan-cmd",
    "cw-fan-cmd",
}
POSITION_ROLES = {
    "cooling-valve",
    "heating-valve",
    "economizer-damper",
    "oa-damper",
    "damper",
    "valve",
    "fan-speed-feedback",
    "pump-speed-feedback",
}


def _role_family(role: str) -> str:
    r = role.replace("_", "-").lower()
    if r in ROLE_BOUNDS:
        return r
    for key in ROLE_BOUNDS:
        if key in r:
            return key
    if r.endswith("-status") or r in STATUS_ROLES:
        return "status"
    if r.endswith("-cmd") or r in COMMAND_ROLES:
        return "command"
    return r


@dataclass
class RoleQuality:
    role: str
    raw: pd.Series
    normalized: pd.Series
    valid: pd.Series
    reason_codes: pd.Series
    valid_sample_count: int
    invalid_sample_count: int
    valid_coverage: float
    reason_counts: dict[str, int]
    first_valid_timestamp: str | None
    last_valid_timestamp: str | None
    quality_confidence: float

    def summary(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "valid_sample_count": self.valid_sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "valid_coverage": self.valid_coverage,
            "reason_counts": dict(self.reason_counts),
            "first_valid_timestamp": self.first_valid_timestamp,
            "last_valid_timestamp": self.last_valid_timestamp,
            "quality_confidence": self.quality_confidence,
        }


@dataclass
class FrameQuality:
    roles: dict[str, RoleQuality] = field(default_factory=dict)
    valid_sample_count: int = 0
    invalid_sample_count: int = 0
    valid_coverage: float = 1.0
    reason_counts: dict[str, int] = field(default_factory=dict)
    first_valid_timestamp: str | None = None
    last_valid_timestamp: str | None = None
    quality_confidence: float = 1.0

    def summary(self) -> dict[str, Any]:
        return {
            "valid_sample_count": self.valid_sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "valid_coverage": self.valid_coverage,
            "reason_counts": dict(self.reason_counts),
            "first_valid_timestamp": self.first_valid_timestamp,
            "last_valid_timestamp": self.last_valid_timestamp,
            "quality_confidence": self.quality_confidence,
            "roles": {k: v.summary() for k, v in self.roles.items()},
        }


def _is_sentinel(num: pd.Series, sentinels: Iterable[float]) -> pd.Series:
    out = pd.Series(False, index=num.index)
    for s in sentinels:
        out = out | np.isclose(num, s, atol=0.0, rtol=0.0) | (num == s)
    return out.fillna(False)


def _scale_position(num: pd.Series) -> pd.Series:
    """Leave 0–1 fractions; map 0–100 percentages to 0–100 for bounds checks."""
    return num


def normalize_role_series(
    series: pd.Series,
    role: str,
    *,
    sentinels: Iterable[float] = DEFAULT_SENTINELS,
    bounds: tuple[float | None, float | None] | None = None,
) -> RoleQuality:
    raw = series.copy()
    family = _role_family(role)
    reason = pd.Series("", index=raw.index, dtype=object)
    valid = pd.Series(True, index=raw.index)

    nulls = raw.isna()
    reason = reason.mask(nulls, REASON_NULL)
    valid = valid & ~nulls

    if family in {"status", "command"} or family in STATUS_ROLES or family in COMMAND_ROLES:
        # Status/command: 0/1 (and 0–100 cmd) are legitimate. Occupancy calendars
        # use occupied/unoccupied strings — those are not NON_NUMERIC.
        num = pd.to_numeric(raw, errors="coerce")
        occ_ok = raw.map(
            lambda x: str(x).strip().lower()
            in {
                "occupied",
                "unoccupied",
                "occ",
                "unocc",
                "true",
                "false",
                "on",
                "off",
                "yes",
                "no",
            }
        )
        non_num = (
            (~nulls)
            & num.isna()
            & ~raw.map(lambda x: isinstance(x, (bool, np.bool_)))
            & ~occ_ok.fillna(False)
        )
        reason = reason.mask(non_num, REASON_NON_NUMERIC)
        valid = valid & ~non_num
        if family in COMMAND_ROLES or str(role).endswith("-cmd"):
            sent = _is_sentinel(num, sentinels)
            reason = reason.mask(sent, REASON_SENTINEL)
            valid = valid & ~sent
            if bounds is None:
                bounds = (0.0, 100.0)
            lo, hi = bounds
            out_of = pd.Series(False, index=raw.index)
            if lo is not None:
                out_of = out_of | (num < lo)
            if hi is not None:
                out_of = out_of | (num > hi)
            # 0–1 fraction commands are in range
            frac = num.between(0.0, 1.0)
            out_of = out_of & ~frac
            reason = reason.mask(out_of & valid, REASON_OUT_OF_RANGE)
            valid = valid & ~out_of
            normalized = num.where(valid, np.nan)
        else:
            sent = _is_sentinel(num, sentinels)
            reason = reason.mask(sent, REASON_SENTINEL)
            valid = valid & ~sent
            normalized = raw.where(valid)
        return _finish(role, raw, normalized, valid, reason)

    num = pd.to_numeric(raw, errors="coerce")
    non_num = (~nulls) & num.isna()
    reason = reason.mask(non_num, REASON_NON_NUMERIC)
    valid = valid & ~non_num

    sent = _is_sentinel(num, sentinels)
    reason = reason.mask(sent, REASON_SENTINEL)
    valid = valid & ~sent

    lo_hi = bounds if bounds is not None else ROLE_BOUNDS.get(family)
    if lo_hi is not None:
        lo, hi = lo_hi
        scaled = _scale_position(num)
        if family in POSITION_ROLES or any(k in family for k in ("valve", "damper", "speed")):
            # Accept 0–1 or 0–100
            in_frac = scaled.between(0.0, 1.0)
            in_pct = scaled.between(0.0, 100.0)
            bad = valid & ~(in_frac | in_pct)
            reason = reason.mask(bad, REASON_OUT_OF_RANGE)
            valid = valid & ~bad
        else:
            out_of = pd.Series(False, index=raw.index)
            if lo is not None:
                out_of = out_of | (scaled < lo)
            if hi is not None:
                out_of = out_of | (scaled > hi)
            # Negative flow/power/current is impossible
            if family.endswith("flow") or family.endswith("power") or family.endswith("current"):
                neg = scaled < 0
                reason = reason.mask(neg & valid, REASON_IMPOSSIBLE)
                valid = valid & ~neg
            reason = reason.mask(out_of & valid, REASON_OUT_OF_RANGE)
            valid = valid & ~out_of

    normalized = num.where(valid, np.nan)
    return _finish(role, raw, normalized, valid, reason)


def _finish(role: str, raw: pd.Series, normalized: pd.Series, valid: pd.Series, reason: pd.Series) -> RoleQuality:
    valid = valid.fillna(False).astype(bool)
    n_valid = int(valid.sum())
    n_invalid = int((~valid).sum())
    cov = n_valid / max(len(valid), 1)
    counts: dict[str, int] = {}
    for code in reason[reason != ""]:
        counts[str(code)] = counts.get(str(code), 0) + 1
    first = last = None
    if n_valid and isinstance(valid.index, pd.DatetimeIndex):
        idx = valid.index[valid]
        first, last = str(idx[0]), str(idx[-1])
    # Confidence: coverage damped by sentinel share
    sent_share = counts.get(REASON_SENTINEL, 0) / max(len(valid), 1)
    confidence = max(0.0, min(1.0, cov * (1.0 - 0.5 * sent_share)))
    return RoleQuality(
        role=role,
        raw=raw,
        normalized=normalized,
        valid=valid,
        reason_codes=reason,
        valid_sample_count=n_valid,
        invalid_sample_count=n_invalid,
        valid_coverage=round(float(cov), 4),
        reason_counts=counts,
        first_valid_timestamp=first,
        last_valid_timestamp=last,
        quality_confidence=round(float(confidence), 4),
    )


def assess_frame(
    df: pd.DataFrame,
    roles: Iterable[str] | None = None,
    *,
    sentinels: Iterable[float] = DEFAULT_SENTINELS,
) -> FrameQuality:
    cols = list(roles) if roles is not None else [c for c in df.columns if c != "timestamp_utc"]
    sentinels = tuple(sentinels)
    fq = FrameQuality()
    any_valid = pd.Series(False, index=df.index)
    totals = {"valid": 0, "invalid": 0}
    merged_reasons: dict[str, int] = {}
    for role in cols:
        if role not in df.columns:
            continue
        rq = normalize_role_series(df[role], role, sentinels=sentinels)
        fq.roles[role] = rq
        any_valid = any_valid | rq.valid
        totals["valid"] += rq.valid_sample_count
        totals["invalid"] += rq.invalid_sample_count
        for k, v in rq.reason_counts.items():
            merged_reasons[k] = merged_reasons.get(k, 0) + v
    n = max(sum(totals.values()), 1)
    fq.valid_sample_count = totals["valid"]
    fq.invalid_sample_count = totals["invalid"]
    fq.valid_coverage = round(totals["valid"] / n, 4)
    fq.reason_counts = merged_reasons
    if any_valid.any() and isinstance(df.index, pd.DatetimeIndex):
        idx = df.index[any_valid]
        fq.first_valid_timestamp = str(idx[0])
        fq.last_valid_timestamp = str(idx[-1])
    if fq.roles:
        fq.quality_confidence = round(
            float(min(r.quality_confidence for r in fq.roles.values())), 4
        )
    return fq


def apply_normalized(
    df: pd.DataFrame,
    quality: FrameQuality,
    *,
    attach_raw_and_flags: bool = True,
) -> pd.DataFrame:
    """Replace analog columns with normalized values.

    One ``assign`` (no per-column insert) so Building 100 frames do not
    fragment and balloon RAM. Set ``attach_raw_and_flags=False`` for FDD
    runs that only need gated values.
    """
    assigns: dict[str, pd.Series] = {}
    for role, rq in quality.roles.items():
        assigns[role] = rq.normalized
        if attach_raw_and_flags:
            raw_col = f"raw:{role}"
            if raw_col not in df.columns:
                assigns[raw_col] = rq.raw
            assigns[f"quality:{role}"] = rq.valid.astype("int8")
    if not assigns:
        return df
    return df.assign(**assigns)
