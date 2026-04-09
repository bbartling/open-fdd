"""
DataFrame column checks for fault rules: presence, numeric usability, coarse range hints.

Used when ``RuleRunner.run(..., input_validation='warn'|'strict')``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

_log = logging.getLogger(__name__)


def _is_effectively_numeric(series: pd.Series) -> Tuple[bool, float]:
    """
    Return (ok, nan_fraction_after_coerce) for non-null cells.
    ok True if at least half of non-null values survive pd.to_numeric.
    """
    mask = series.notna()
    if not mask.any():
        return True, 0.0
    coerced = pd.to_numeric(series[mask], errors="coerce")
    bad = coerced.isna().sum()
    n = int(mask.sum())
    frac = float(bad) / float(n) if n else 0.0
    return frac <= 0.5, frac


def _range_hint(alias: str, col: str, series: pd.Series) -> Optional[str]:
    """Heuristic message when values look like percent (always >1) vs fraction."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    mx = float(s.max())
    mn = float(s.min())
    if mn >= 0 and mx > 1.0 and mx <= 100.0 and "Command" in alias:
        return (
            f"input '{alias}' -> column '{col}' looks like 0–100% command signals; "
            "cookbook thresholds often assume 0–1. Consider normalize_cmd(...) in the expression."
        )
    return None


def validate_rule_inputs(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    *,
    rule_name: str,
    timestamp_col: Optional[str],
    mode: str = "off",
) -> List[str]:
    """
    Validate resolved rule inputs against ``df``.

    Returns a list of human-readable issue strings (empty if none).
    Does not mutate ``df``.

    ``mode``: ``'off'`` (no checks), ``'warn'`` (collect issues), ``'strict'`` (collect;
    caller should raise if non-empty).
    """
    if mode not in ("off", "warn", "strict"):
        raise ValueError("mode must be 'off', 'warn', or 'strict'")
    if mode == "off":
        return []

    issues: List[str] = []
    for alias, col in col_map.items():
        if not col:
            issues.append(f"rule '{rule_name}': empty column mapping for input '{alias}'")
            continue
        if col not in df.columns:
            issues.append(
                f"rule '{rule_name}': input '{alias}' maps to missing column '{col}'"
            )
            continue
        if timestamp_col and col == timestamp_col:
            continue
        ser = df[col]
        ok, frac = _is_effectively_numeric(ser)
        if not ok:
            issues.append(
                f"rule '{rule_name}': column '{col}' (input '{alias}') is largely non-numeric "
                f"after coercion (~{frac:.0%} of non-null values become NaN)"
            )
        hint = _range_hint(alias, col, ser)
        if hint:
            issues.append(hint)

    for msg in issues:
        if mode == "warn":
            _log.warning("FDD input validation: %s", msg)
    return issues


def raise_if_strict_issues(issues: List[str]) -> None:
    if issues:
        raise ValueError("FDD input validation failed:\n" + "\n".join(issues))
