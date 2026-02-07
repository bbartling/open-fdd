"""
Built-in fault checks for the config-driven engine.

Each check operates on pandas Series/DataFrames and returns a boolean mask.
"""

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def check_bounds(series: pd.Series, low: float, high: float) -> pd.Series:
    """
    True where values are outside [low, high].
    """
    return (series < low) | (series > high)


def check_flatline(
    series: pd.Series,
    tolerance: float = 0.000001,
    window: int = 12,
) -> pd.Series:
    """
    True where the rolling spread (max - min) is below tolerance.
    Indicates sensor flatlined.
    """
    spread = series.rolling(window=window).apply(
        lambda x: x.max() - x.min() if len(x) == window else float("nan"),
        raw=True,
    )
    return (spread < tolerance) & spread.notna()


def check_expression(
    df: pd.DataFrame,
    expr: str,
    col_map: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
) -> pd.Series:
    """
    Evaluate a pandas expression string against the DataFrame.

    Expression can use:
    - Column aliases from col_map (e.g. duct_static -> df["dp"])
    - Param names from params (e.g. static_err_thres -> 0.1)

    Example expression:
        (duct_static < duct_static_setpoint - static_err_thres) & (vfd >= vfd_max)
    """
    params = params or {}
    # Build eval namespace: map alias -> Series, param -> value, np for element-wise ops
    namespace = {"np": np}
    for alias, col in col_map.items():
        if col in df.columns:
            namespace[alias] = df[col]
    for k, v in params.items():
        namespace[k] = v
    # Restrict to only our names for safety
    allowed = set(namespace.keys())
    # Minimal safety: no builtins, no imports
    try:
        result = pd.eval(expr, local_dict=namespace, global_dict={})
    except Exception:
        # Fallback: use Python eval with restricted namespace
        result = eval(expr, {"__builtins__": {}}, namespace)
    if isinstance(result, pd.Series):
        return result.fillna(False)
    return pd.Series(bool(result), index=df.index)


def check_hunting(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    params: Dict[str, Any],
) -> pd.Series:
    """
    AHU PID hunting: fault when excessive operating state changes in a window.
    Counts changes across economizer, VFD, heating, cooling modes.
    """
    delta_os_max = params.get("delta_os_max", 10)
    ahu_min_oa_dpr = params.get("ahu_min_oa_dpr", 0.1)
    window = params.get("window", 60)

    def _get_series(name: str) -> pd.Series:
        col = col_map.get(name)
        if col and col in df.columns:
            s = df[col].fillna(0)
            if (s > 1.0).any():
                s = s / 100.0
            return s
        return pd.Series(0.0, index=df.index)

    economizer_sig = _get_series("Damper_Position_Command")
    supply_vfd_speed = _get_series("Supply_Fan_Speed_Command")
    heating_sig = _get_series("Heating_Valve_Command")
    cooling_sig = _get_series("Cooling_Valve_Command")

    os_change = (
        (economizer_sig > 0).astype(int)
        + (supply_vfd_speed > ahu_min_oa_dpr).astype(int)
        + (heating_sig > 0).astype(int)
        + (cooling_sig > 0).astype(int)
    )
    os_change_diff = os_change.diff().abs().fillna(0)
    os_change_sum = os_change_diff.rolling(window=window).sum()
    return os_change_sum > delta_os_max


def check_oa_fraction(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    params: Dict[str, Any],
) -> pd.Series:
    """
    AHU FC6: OA fraction calc error or AHU not maintaining design airflow.
    Fault when |OA_frac_calc - OA_min| > threshold in non-economizer modes.
    """

    def _get(name: str) -> pd.Series:
        col = col_map.get(name)
        return df[col] if col and col in df.columns else pd.Series(0.0, index=df.index)

    airflow_err_thres = params.get("airflow_err_thres", 0.1)
    ahu_min_oa_cfm_design = params.get("ahu_min_oa_cfm_design", 1000.0)
    oat_rat_delta_min = params.get("oat_rat_delta_min", 5.0)
    ahu_min_oa_dpr = params.get("ahu_min_oa_dpr", 0.1)

    rat = _get("Return_Air_Temperature_Sensor")
    oat = _get("Outside_Air_Temperature_Sensor")
    mat = _get("Mixed_Air_Temperature_Sensor")
    supply_fan_air_volume = _get("Supply_Fan_Air_Flow_Sensor")
    supply_vfd_speed = _get("Supply_Fan_Speed_Command")
    economizer_sig = _get("Damper_Position_Command")
    heating_sig = _get("Heating_Valve_Command")
    cooling_sig = _get("Cooling_Valve_Command")

    if (supply_vfd_speed > 1.0).any():
        supply_vfd_speed = supply_vfd_speed / 100.0
    if (economizer_sig > 1.0).any():
        economizer_sig = economizer_sig / 100.0
    if (heating_sig > 1.0).any():
        heating_sig = heating_sig / 100.0
    if (cooling_sig > 1.0).any():
        cooling_sig = cooling_sig / 100.0

    rat_minus_oat = (rat - oat).abs()
    denom = oat - rat
    percent_oa_calc = np.where(denom != 0, (mat - rat) / denom, 0)
    percent_oa_calc = np.clip(percent_oa_calc, 0, None)
    perc_OAmin = np.where(
        supply_fan_air_volume > 0, ahu_min_oa_cfm_design / supply_fan_air_volume, 0
    )
    percent_oa_calc_minus_perc_OAmin = np.abs(percent_oa_calc - perc_OAmin)

    os1 = (
        (rat_minus_oat >= oat_rat_delta_min)
        & (percent_oa_calc_minus_perc_OAmin > airflow_err_thres)
        & (heating_sig > 0.0)
        & (supply_vfd_speed > 0.0)
    )
    os4 = (
        (rat_minus_oat >= oat_rat_delta_min)
        & (percent_oa_calc_minus_perc_OAmin > airflow_err_thres)
        & (heating_sig == 0.0)
        & (cooling_sig > 0.0)
        & (supply_vfd_speed > 0.0)
        & (economizer_sig <= ahu_min_oa_dpr)
    )
    return pd.Series(os1 | os4, index=df.index)


def check_erv_efficiency(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    params: Dict[str, Any],
) -> pd.Series:
    """
    AHU heat exchanger: ERV effectiveness outside expected range.
    """

    def _get(name: str) -> pd.Series:
        col = col_map.get(name)
        return df[col] if col and col in df.columns else pd.Series(0.0, index=df.index)

    erv_oat_enter = _get("ERV_Outside_Air_Temperature_Sensor")
    erv_oat_leaving = _get("ERV_Discharge_Air_Temperature_Sensor")
    erv_eat_enter = _get("ERV_Return_Air_Temperature_Sensor")

    erv_eff_min_htg = params.get("erv_efficiency_min_heating", 0.5)
    erv_eff_max_htg = params.get("erv_efficiency_max_heating", 0.9)
    erv_eff_min_clg = params.get("erv_efficiency_min_cooling", 0.5)
    erv_eff_max_clg = params.get("erv_efficiency_max_cooling", 0.9)
    oat_low = params.get("oat_low_threshold", 55.0)
    oat_high = params.get("oat_high_threshold", 65.0)
    oat_rat_delta_min = params.get("oat_rat_delta_min", 5.0)

    oat_rat_delta = (erv_oat_enter - erv_eat_enter).abs()
    denom = erv_eat_enter - erv_oat_enter
    erv_effectiveness = np.where(
        denom != 0, (erv_oat_leaving - erv_oat_enter) / denom, 0
    )

    heating_mode = erv_oat_enter < oat_low
    cooling_mode = erv_oat_enter > oat_high

    low_htg = heating_mode & (erv_effectiveness < erv_eff_min_htg)
    high_htg = heating_mode & (erv_effectiveness > erv_eff_max_htg)
    low_clg = cooling_mode & (erv_effectiveness < erv_eff_min_clg)
    high_clg = cooling_mode & (erv_effectiveness > erv_eff_max_clg)

    fault = (oat_rat_delta >= oat_rat_delta_min) & (
        low_htg | high_htg | low_clg | high_clg
    )
    return pd.Series(fault, index=df.index)
