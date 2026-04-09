"""
Config-driven fault rule runner.

Loads YAML rule configs and evaluates them against pandas DataFrames.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import yaml

from open_fdd.engine.checks import (
    check_bounds,
    check_expression,
    check_flatline,
    check_hunting,
    check_oa_fraction,
    check_erv_efficiency,
)
from open_fdd.engine.input_validation import (
    raise_if_strict_issues,
    validate_rule_inputs,
)
from open_fdd.engine.rule_schema import coerce_rule_params as coerce_rule_params_dict

_log = logging.getLogger(__name__)


def load_rule(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a rule config from YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Order for column_map lookup: first match wins (manifest may key by any vocabulary).
_ONTOLOGY_MAP_FIELDS = ("brick", "haystack", "dbo", "s223", "223p")


def _resolve_input_column(key: str, val: Any, global_col_map: Dict[str, str]) -> str:
    """
    Map a rule input to a DataFrame column name.

    Without column_map, uses inline ``column`` or the input key.
    With column_map, tries ontology labels on the input dict in order
    (brick, haystack, dbo, s223, 223p), then Brick disambiguation
    ``BrickClass|column``, then ``column`` and ``key``.
    """
    if isinstance(val, str):
        default_col = val
        inp: Dict[str, Any] = {}
    else:
        inp = val if isinstance(val, dict) else {}
        default_col = inp.get("column", key)

    if not global_col_map:
        return default_col

    for field in _ONTOLOGY_MAP_FIELDS:
        label = inp.get(field)
        if label:
            mapped = global_col_map.get(label)
            if mapped is not None:
                return mapped

    brick_class = inp.get("brick")
    if brick_class:
        return (
            global_col_map.get(f"{brick_class}|{default_col}")
            or global_col_map.get(default_col)
            or global_col_map.get(key)
            or default_col
        )

    return global_col_map.get(default_col) or global_col_map.get(key) or default_col


def col_map_for_rule(rule: Dict[str, Any], global_col_map: Dict[str, str]) -> Dict[str, str]:
    """Resolved logical input name → DataFrame column for one rule."""
    inputs = rule.get("inputs", {})
    return {
        key: _resolve_input_column(key, val, global_col_map)
        for key, val in inputs.items()
    }


def _resolve_bounds(bounds: Any, units: str = "imperial") -> Optional[List[float]]:
    """Resolve bounds: [low, high] or {imperial: [...], metric: [...]}."""
    if bounds is None:
        return None
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        return list(bounds)
    if isinstance(bounds, dict):
        return bounds.get(units) or bounds.get("imperial")
    return None


def bounds_map_from_rule(
    rule: Dict[str, Any], units: str = "imperial"
) -> Dict[str, tuple]:
    """
    Extract {brick_name: (low, high)} from a bounds-type rule.
    Use for episode analysis so bounds stay in sync with the YAML.
    """
    out = {}
    for key, inp in rule.get("inputs", {}).items():
        if isinstance(inp, str):
            continue
        brick = inp.get("brick", key)
        raw = inp.get("bounds", rule.get("bounds"))
        resolved = _resolve_bounds(raw, units)
        if resolved and len(resolved) == 2:
            out[brick] = (float(resolved[0]), float(resolved[1]))
    return out


def load_rules_from_dir(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Load all .yaml rule configs from a directory."""
    rules_dir = Path(path)
    if not rules_dir.is_dir():
        return []
    rules = []
    for f in sorted(rules_dir.glob("*.yaml")):
        rules.append(load_rule(f))
    return rules


class RuleRunner:
    """
    Runs config-driven fault rules against pandas DataFrames.

    Example:
        runner = RuleRunner("path/to/rules")
        df_result = runner.run(df)
    """

    def __init__(
        self,
        rules_path: Optional[Union[str, Path]] = None,
        rules: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Args:
            rules_path: Directory containing .yaml rule files.
            rules: List of rule dicts (alternative to loading from path).
        """
        self._rules: List[Dict[str, Any]] = []
        if rules_path:
            self._rules = load_rules_from_dir(rules_path)
        elif rules:
            self._rules = rules

    def add_rule(self, rule: Dict[str, Any]) -> None:
        """Add a single rule config."""
        self._rules.append(rule)

    def run(
        self,
        df: pd.DataFrame,
        timestamp_col: Optional[str] = None,
        rolling_window: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        skip_missing_columns: bool = False,
        column_map: Optional[Dict[str, str]] = None,
        input_validation: Optional[str] = None,
        coerce_rule_params: bool = True,
    ) -> pd.DataFrame:
        """
        Run all rules against the DataFrame.

        Args:
            df: Input DataFrame with time-series data.
            timestamp_col: Column name for timestamps (used for time-based checks).
            rolling_window: Consecutive samples required to flag fault (None = any).
            params: Override params merged into each rule (e.g. units="metric" for bounds).
            skip_missing_columns: If True, skip rules with missing columns instead of raising.
            column_map: Optional {rule_input: df_column} from Brick/SPARQL. Overrides rule inputs.
            input_validation: ``None``/``'off'`` (default), ``'warn'`` (log dtype/presence issues),
                or ``'strict'`` (raise ``ValueError`` on missing columns or largely non-numeric inputs).
            coerce_rule_params: If True (default), validate/coerce ``schedule`` / ``weather_band`` and
                string numerics in merged rule params via Pydantic (see :mod:`open_fdd.engine.rule_schema`).

        Returns:
            DataFrame with original columns plus fault flag columns (e.g. rule_name_flag).
        """
        result = df.copy()
        if timestamp_col is None and "timestamp" in df.columns:
            timestamp_col = "timestamp"
        run_params = params or {}
        skip_missing = skip_missing_columns
        global_col_map = column_map or {}
        iv_mode = (input_validation or "off").lower()
        if iv_mode not in ("off", "warn", "strict"):
            raise ValueError(
                "input_validation must be None, 'off', 'warn', or 'strict'"
            )

        for rule in self._rules:
            flag_name = rule.get("flag", f"{rule.get('name', 'rule')}_flag")
            col_map = col_map_for_rule(rule, global_col_map)
            rule_eff = dict(rule)
            merged_p = {**(rule.get("params") or {}), **run_params}
            if coerce_rule_params:
                try:
                    rule_eff["params"] = coerce_rule_params_dict(merged_p)
                except Exception as e:
                    raise RuntimeError(
                        f"Rule '{rule.get('name', '?')}' has invalid params: {e}"
                    ) from e
            else:
                rule_eff["params"] = merged_p

            if iv_mode != "off":
                issues = validate_rule_inputs(
                    result,
                    col_map,
                    rule_name=str(rule.get("name", "?")),
                    timestamp_col=timestamp_col,
                    mode=iv_mode,
                )
                if iv_mode == "strict":
                    raise_if_strict_issues(issues)

            try:
                mask = self._evaluate_rule(
                    rule_eff, result, timestamp_col, run_params, global_col_map
                )
                # Per-rule rolling_window (params.rolling_window), else global
                rw = (rule.get("params") or {}).get("rolling_window")
                if rw is None:
                    rw = rule.get("rolling_window")
                if rw is None:
                    rw = rolling_window
                if rw and rw > 1:
                    rolling_sum = mask.astype(int).rolling(window=rw).sum()
                    result[flag_name] = (rolling_sum >= rw).astype(int)
                else:
                    result[flag_name] = mask.astype(int)
            except (KeyError, NameError) as e:
                if skip_missing:
                    _log.warning(
                        "Skipping rule %r (flag %r): %s: %s",
                        rule.get("name", "?"),
                        flag_name,
                        type(e).__name__,
                        e,
                    )
                    continue
                raise RuntimeError(
                    f"Rule '{rule.get('name', '?')}' failed (missing column?): {e}"
                ) from e
            except Exception as e:
                raise RuntimeError(f"Rule '{rule.get('name', '?')}' failed: {e}") from e

        return result

    def _evaluate_rule(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        timestamp_col: Optional[str],
        run_params: Optional[Dict[str, Any]] = None,
        column_map: Optional[Dict[str, str]] = None,
    ) -> pd.Series:
        """Evaluate a single rule and return boolean fault mask."""
        rule_type = rule.get("type", "expression")
        inputs = rule.get("inputs", {})
        params = {**(rule.get("params") or {}), **(run_params or {})}
        global_col_map = column_map or {}

        # Map logical input keys (e.g. Brick class names) → DataFrame columns via column_map.
        # The AFDD stack builds that map from TTL; engine-only callers pass a dict or manifest.
        col_map = {
            key: _resolve_input_column(key, val, global_col_map)
            for key, val in inputs.items()
        }

        if rule_type == "bounds":
            return self._run_bounds(rule, df, col_map, params)
        if rule_type == "flatline":
            return self._run_flatline(rule, df, col_map)
        if rule_type == "expression":
            return self._run_expression(rule, df, col_map, params, timestamp_col)
        if rule_type == "hunting":
            return self._run_hunting(rule, df, col_map, params)
        if rule_type == "oa_fraction":
            return self._run_oa_fraction(rule, df, col_map, params)
        if rule_type == "erv_efficiency":
            return self._run_erv_efficiency(rule, df, col_map, params)
        raise ValueError(f"Unknown rule type: {rule_type}")

    def _run_bounds(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> pd.Series:
        """Run bounds check(s). Supports units=metric for unit-aware bounds."""
        params = params or {}
        units = params.get("units", "imperial")
        inputs = rule.get("inputs", {})
        out = pd.Series(False, index=df.index)
        for key, col in col_map.items():
            if col not in df.columns:
                continue
            inp = inputs.get(key, {})
            if isinstance(inp, str):
                continue
            raw_bounds = inp.get("bounds", rule.get("bounds"))
            bounds = _resolve_bounds(raw_bounds, units)
            if not bounds or len(bounds) != 2:
                continue
            low, high = bounds
            out |= check_bounds(df[col], low, high)
        return out

    def _run_flatline(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
    ) -> pd.Series:
        """Run flatline check."""
        params = rule.get("params", {})
        tolerance = params.get("tolerance", 0.000001)
        window = params.get("window", 12)  # samples
        out = pd.Series(False, index=df.index)
        for col in col_map.values():
            if col not in df.columns:
                continue
            out |= check_flatline(df[col], tolerance=tolerance, window=window)
        return out

    def _run_expression(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
        params: Dict[str, Any],
        timestamp_col: Optional[str] = None,
    ) -> pd.Series:
        """Run expression-based rule."""
        expr = rule.get("expression", "")
        if not expr.strip():
            return pd.Series(False, index=df.index)
        return check_expression(df, expr, col_map, params, timestamp_col=timestamp_col)

    def _run_hunting(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
        params: Dict[str, Any],
    ) -> pd.Series:
        """Run PID hunting / excessive state changes rule."""
        return check_hunting(df, col_map, params)

    def _run_oa_fraction(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
        params: Dict[str, Any],
    ) -> pd.Series:
        """Run OA fraction / design airflow rule."""
        return check_oa_fraction(df, col_map, params)

    def _run_erv_efficiency(
        self,
        rule: Dict[str, Any],
        df: pd.DataFrame,
        col_map: Dict[str, str],
        params: Dict[str, Any],
    ) -> pd.Series:
        """Run ERV effectiveness rule."""
        return check_erv_efficiency(df, col_map, params)
