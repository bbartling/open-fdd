"""
Config-driven fault rule runner.

Loads YAML rule configs and evaluates them against pandas DataFrames.
"""

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


def load_rule(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a rule config from YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_bounds(bounds: Any, units: str = "imperial") -> Optional[List[float]]:
    """Resolve bounds: [low, high] or {imperial: [...], metric: [...]}."""
    if bounds is None:
        return None
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        return list(bounds)
    if isinstance(bounds, dict):
        return bounds.get(units) or bounds.get("imperial")
    return None


def bounds_map_from_rule(rule: Dict[str, Any], units: str = "imperial") -> Dict[str, tuple]:
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

        Returns:
            DataFrame with original columns plus fault flag columns (e.g. rule_name_flag).
        """
        result = df.copy()
        if timestamp_col is None and "timestamp" in df.columns:
            timestamp_col = "timestamp"
        run_params = params or {}
        skip_missing = skip_missing_columns
        global_col_map = column_map or {}

        for rule in self._rules:
            flag_name = rule.get("flag", f"{rule.get('name', 'rule')}_flag")
            try:
                mask = self._evaluate_rule(
                    rule, result, timestamp_col, run_params, global_col_map
                )
                if rolling_window and rolling_window > 1:
                    rolling_sum = mask.astype(int).rolling(window=rolling_window).sum()
                    result[flag_name] = (rolling_sum >= rolling_window).astype(int)
                else:
                    result[flag_name] = mask.astype(int)
            except (KeyError, NameError) as e:
                if skip_missing:
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

        # Resolve column mappings: BRICK class first, then rule input name
        # column_map keys can be Brick class (Supply_Air_Temperature_Sensor),
        # BrickClass|rule_input for disambiguation, or rule input (sat)
        col_map = {}
        for key, val in inputs.items():
            if isinstance(val, str):
                col = val
                brick_class = None
            else:
                inp = val if isinstance(val, dict) else {}
                col = inp.get("column", key)
                brick_class = inp.get("brick")
            # Lookup order: Brick class, BrickClass|column (disambiguation), column, key, literal
            resolved = col
            if global_col_map:
                if brick_class:
                    resolved = (
                        global_col_map.get(brick_class)
                        or global_col_map.get(f"{brick_class}|{col}")
                        or global_col_map.get(col)
                        or global_col_map.get(key)
                        or col
                    )
                else:
                    resolved = (
                        global_col_map.get(col)
                        or global_col_map.get(key)
                        or col
                    )
            col_map[key] = resolved

        if rule_type == "bounds":
            return self._run_bounds(rule, df, col_map, params)
        if rule_type == "flatline":
            return self._run_flatline(rule, df, col_map)
        if rule_type == "expression":
            return self._run_expression(rule, df, col_map, params)
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
    ) -> pd.Series:
        """Run expression-based rule."""
        expr = rule.get("expression", "")
        if not expr.strip():
            return pd.Series(False, index=df.index)
        return check_expression(df, expr, col_map, params)

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
