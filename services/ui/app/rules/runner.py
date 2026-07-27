"""Run the 50-rule pandas cookbook with explicit skip / not-applicable behavior."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.rules import cookbook_catalog as cb
from app.rules.base import (
    RuleResult,
    confirm_fault,
    equipment_off,
    error_result,
    finalize_result,
    hours_true,
    not_applicable,
    params_fingerprint,
    skipped,
)
from app.rules.operational_gate import RULE_GATES, resolve_operational_mask, should_skip_equipment_off
from app.site_model import equipment_type_from_id, resolve_equipment_type


def infer_equipment_kind(
    equipment_id: str = "",
    *,
    equipment_type: str = "",
    df: pd.DataFrame | None = None,
    role_map: dict | None = None,
) -> str:
    """Map equipment to cookbook kind using resolved type (attrs / map / id)."""
    t = resolve_equipment_type(
        equipment_id or (str(df.attrs.get("equipment_id", "")) if df is not None else ""),
        df=df,
        role_map=role_map,
        explicit=equipment_type or None,
    )
    return {
        "AHU": "ahu",
        "VAV": "vav",
        "CHW_PLANT": "chiller",
        "CHILLER": "chiller",
        "COOLING_TOWER": "cooling_tower",
        "BOILER": "boiler",
        "HP": "heatpump",
        "WEATHER": "weather",
        "METER": "meter",
        "UNKNOWN": "unknown",
    }.get(t, "unknown")


def merge_weather(df: pd.DataFrame, weather: pd.DataFrame | None) -> pd.DataFrame:
    """Align/enrich web weather onto an equipment frame, then resolve effective OAT.

    Adds ``oa_t_effective`` / ``oa_t_effective_source`` / optional ``bas_oa_t`` before
    missing-role checks. Never overwrites a real BAS ``oa_t`` column.
    """
    from app.weather_psychrometrics import dewpoint_f_from_db_rh, enrich_weather_frame, wetbulb_f_stull
    from app.weather_resolver import apply_effective_oat_columns

    out = df.copy()
    if weather is not None and not weather.empty:
        wx = enrich_weather_frame(weather).reindex(out.index)
        for col in wx.columns:
            if col not in out.columns:
                out[col] = wx[col]
            elif col.startswith("wx_") and out[col].notna().sum() == 0:
                out[col] = wx[col]
    # Derive dewpoint / wet-bulb on the equipment frame when RH landed
    if ("web-outside-air-dewpoint" not in out.columns or out["web-outside-air-dewpoint"].notna().sum() == 0) and {
        "web-outside-air-temp",
        "web-outside-air-humidity",
    }.issubset(out.columns):
        out["web-outside-air-dewpoint"] = dewpoint_f_from_db_rh(out["web-outside-air-temp"], out["web-outside-air-humidity"])
    if ("web-outside-air-wetbulb" not in out.columns or out["web-outside-air-wetbulb"].notna().sum() == 0) and {
        "web-outside-air-temp",
        "web-outside-air-humidity",
    }.issubset(out.columns):
        out["web-outside-air-wetbulb"] = wetbulb_f_stull(out["web-outside-air-temp"], out["web-outside-air-humidity"])
    return apply_effective_oat_columns(out)


def weather_available(df: pd.DataFrame) -> bool:
    """True when web weather can support free-cool (dewpoint present or derivable)."""
    if "web-outside-air-dewpoint" in df.columns and df["web-outside-air-dewpoint"].notna().any():
        return True
    if "web-outside-air-temp" in df.columns and "web-outside-air-humidity" in df.columns:
        return df["web-outside-air-temp"].notna().any() and df["web-outside-air-humidity"].notna().any()
    return False


def econ3_compute(d: pd.DataFrame, p: dict, poll: float, wx_ok: bool = True) -> pd.Series:
    """Mech cooling while free cooling available without integrated OA damper (web weather)."""
    from app.rules.economizer_weather import econ3_compute as _econ3

    return _econ3(d, p, poll, wx_ok=wx_ok)


def _confirm_seconds(rule: cb.CookbookRule, params: dict) -> float:
    if "confirm_min" in params:
        return float(params["confirm_min"]) * 60.0
    return rule.confirm_seconds


def _missing_roles(rule: cb.CookbookRule, df: pd.DataFrame) -> list[str]:
    from app.weather_resolver import oat_meteo_availability

    if rule.id == "OAT-METEO":
        ok, reasons = oat_meteo_availability(df)
        return [] if ok else reasons
    if rule.id == "ECON-3":
        from app.rules.economizer_weather import web_weather_missing_reasons

        missing_wx = web_weather_missing_reasons(df)
        base = []
        for role in ("outside-air-damper", "cooling-valve"):
            if role not in df.columns or df[role].notna().sum() == 0:
                base.append(role)
        return base + missing_wx
    if rule.id == "ECON-7":
        from app.rules.economizer_weather import mechanical_proof_mask, web_weather_missing_reasons

        missing_wx = web_weather_missing_reasons(df)
        base = []
        if "outside-air-damper" not in df.columns or df["outside-air-damper"].notna().sum() == 0:
            base.append("outside-air-damper")
        has_demand = "cooling-valve" in df.columns and df["cooling-valve"].notna().any()
        if not has_demand:
            _, kind = mechanical_proof_mask(df)
            has_demand = bool(kind)
        if not has_demand:
            base.append("cooling-valve|dx_or_chiller_proof")
        return base + missing_wx
    if rule.id in {"MECH-OAT-1", "ECON-6"}:
        if "web-outside-air-temp" not in df.columns or not df["web-outside-air-temp"].notna().any():
            return ["web-outside-air-temp"]
        if rule.id == "ECON-6":
            if "outside-air-damper" not in df.columns or not df["outside-air-damper"].notna().any():
                return ["outside-air-damper"]
        return []
    if rule.id == "CHW-NOLOAD-1":
        from app.load_satisfaction import AHU_SAT_COL, ZONE_SAT_COL
        from app.rules.economizer_weather import mechanical_proof_mask

        run, kind = mechanical_proof_mask(df, equipment_type="CHILLER")
        if not kind:
            return ["chiller_or_pump_proof"]
        has_zone = ZONE_SAT_COL in df.columns and df[ZONE_SAT_COL].notna().any()
        has_ahu = AHU_SAT_COL in df.columns and df[AHU_SAT_COL].notna().any()
        if not has_zone and not has_ahu:
            return ["building-zone-load-satisfied|building-ahu-load-satisfied"]
        return []
    if rule.id == "SCHED-247":
        proofs = (
            "fan-status",
            "pump-status",
            "chw-pump-status",
            "hw-pump-status",
            "chiller-status",
            "compressor-status",
            "tower-fan-cmd",
            "cw-fan-cmd",
            "fan-cmd",
            "chw-pump-cmd",
            "hw-pump-cmd",
            "duct-static-pressure",
            "chw-diff-pressure",
        )
        if any(r in df.columns and df[r].notna().any() for r in proofs):
            return []
        return ["fan_or_pump_status_or_cmd_or_pressure"]
    if rule.sensor_sweep:
        present = [r for r in cb.SWEEP_SENSOR_ROLES if r in df.columns and df[r].notna().any()]
        return [] if present else ["any sensor role from sweep list"]
    if rule.control_output_sweep:
        from app.rules.pid_hunting import control_outputs_present

        return [] if control_outputs_present(df) else ["any 0-100% control output (valve/damper/fan/pump cmd)"]
    missing = []
    for role in rule.required_roles:
        if role == "outside-air-temp":
            # Physics rules may use oa_t_effective (web primary / BAS fallback)
            if "outside-air-temp" in df.columns and df["outside-air-temp"].notna().any():
                continue
            if "oa_t_effective" in df.columns and df["oa_t_effective"].notna().any():
                continue
            missing.append(role)
            continue
        if role == "web-outside-air-temp":
            if role not in df.columns or df[role].notna().sum() == 0:
                missing.append(role)
            continue
        if role not in df.columns or df[role].notna().sum() == 0:
            missing.append(role)
    if rule.id in {"CW-OPT-1", "CW-APR-1", "CW-FAN-1"} and (
        "web-outside-air-wetbulb" not in df.columns or df["web-outside-air-wetbulb"].notna().sum() == 0
    ):
        missing.append("web-outside-air-wetbulb")
    if rule.id in {"CW-APR-1", "CW-FAN-1"}:
        fan_ok = any(
            r in df.columns and df[r].notna().any()
            for r in ("tower-fan-cmd", "cw-fan-cmd", "fan-cmd")
        )
        if not fan_ok:
            missing.append("tower_fan_cmd|cw_fan_cmd|fan_cmd")
    return missing


_TEMP_PLOT_MARKERS = (
    "temp",
    "temperature",
    "dewpoint",
    "wetbulb",
)
_PRESSURE_PLOT_MARKERS = ("static-pressure", "pressure", "dp", "differential-pressure")
_TEMP_PCT_COMPANIONS = ("outside-air-damper", "cooling-valve", "heating-valve", "reheat-valve")
_PRESSURE_PCT_COMPANIONS = (
    "fan-cmd",
    "return-fan-cmd",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "pump-cmd",
    "tower-fan-cmd",
    "cw-fan-cmd",
)
_FAN_CMD_ONLY_RULES = frozenset({"FC1", "AHU-DUCTHI", "TRIM-1", "CMD-1", "SCHED-1", "SCHED-247"})
# Motor/fan proof lane on every rule plot: real status first, else 0/1 derived from cmd.
_STATUS_BOOL_ROLES = (
    "fan-status",
    "pump-status",
    "chw-pump-status",
    "hw-pump-status",
    "compressor-status",
    "chiller-status",
)
_STATUS_CMD_FALLBACKS = (
    "fan-cmd",
    "return-fan-cmd",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "pump-cmd",
    "tower-fan-cmd",
    "cw-fan-cmd",
)
_OAT_PLOT_ROLES = ("outside-air-temp", "web-outside-air-temp")


def _role_is_temp(role: str) -> bool:
    r = role.lower()
    return any(m in r for m in _TEMP_PLOT_MARKERS) or r.endswith("-temp") or r.endswith("-sp") and "temp" in r


def _role_is_pressure(role: str) -> bool:
    r = role.lower()
    return any(m in r for m in _PRESSURE_PLOT_MARKERS)


def _plot_series_for_rule(rule: cb.CookbookRule, d: pd.DataFrame) -> dict[str, pd.Series]:
    """Attach rule input columns for plotting (unit-separated in the chart layer).

    Temperature-primary plots pair with OA damper + heat/cool valves (not fan %).
    Pressure-primary / FC1 plots pair with fan or pump speeds.
    """
    out: dict[str, pd.Series] = {}
    if rule.control_output_sweep:
        from app.rules.pid_hunting import iter_control_output_series

        for label, series in iter_control_output_series(d):
            out[label] = series
        return out
    roles = list(rule.required_roles)
    if rule.sensor_sweep:
        roles = [r for r in cb.SWEEP_SENSOR_ROLES if r in d.columns]
    for role in roles:
        if role in d.columns and d[role].notna().any():
            out[role] = d[role]

    has_temp = any(_role_is_temp(r) for r in out)
    has_pressure = any(_role_is_pressure(r) for r in out)
    allow_fan_cmd = rule.id in _FAN_CMD_ONLY_RULES or has_pressure

    if has_temp and not has_pressure:
        if not allow_fan_cmd:
            out.pop("fan-cmd", None)
            out.pop("return-fan-cmd", None)
        for c in _TEMP_PCT_COMPANIONS:
            if c in d.columns and d[c].notna().any():
                out[c] = d[c]
    if has_pressure or rule.id in {"FC1", "AHU-DUCTHI", "TRIM-1"}:
        for c in _PRESSURE_PCT_COMPANIONS:
            if c in d.columns and d[c].notna().any():
                out[c] = d[c]
    if rule.id == "SCHED-247":
        for c in (
            "fan-status",
            "pump-status",
            "chw-pump-status",
            "hw-pump-status",
            "fan-cmd",
            "chw-pump-cmd",
            "hw-pump-cmd",
        ):
            if c in d.columns and d[c].notna().any():
                out[c] = d[c]
    _attach_motor_status_lane(out, d)
    _attach_dewpoint_line(out, d)
    return out


def _attach_motor_status_lane(out: dict[str, pd.Series], d: pd.DataFrame) -> None:
    """Add one 0/1 motor/fan status lane to every rule plot when a proof signal exists."""
    if not out:
        return
    if any(r in out for r in _STATUS_BOOL_ROLES):
        return
    for role in _STATUS_BOOL_ROLES:
        if role in d.columns and d[role].notna().any():
            out[role] = d[role]
            return
    for role in _STATUS_CMD_FALLBACKS:
        if role in d.columns and d[role].notna().any():
            out["motor-on"] = (cb.norm_cmd(d[role]).fillna(0) > 0.05).astype(int)
            return


def _attach_dewpoint_line(out: dict[str, pd.Series], d: pd.DataFrame) -> None:
    """Temperature plots that show outside-air temp also get the web outdoor dewpoint line."""
    if "web-outside-air-dewpoint" in out:
        return
    if not any(r in out for r in _OAT_PLOT_ROLES):
        return
    if "web-outside-air-dewpoint" in d.columns and d["web-outside-air-dewpoint"].notna().any():
        out["web-outside-air-dewpoint"] = d["web-outside-air-dewpoint"]


def _params_for_rule(rule: cb.CookbookRule, params_by_rule: dict[str, dict]) -> dict:
    p = dict(rule.defaults())
    spec = RULE_GATES.get(rule.id)
    if spec and spec.kind != "always":
        p.setdefault("require_operational_gate", 1.0)
        p.setdefault("startup_delay_min", spec.startup_delay_seconds / 60.0)
        p.setdefault("minimum_active_coverage_pct", spec.minimum_active_coverage_pct)
    else:
        p.setdefault("require_operational_gate", 0.0)
    overrides = dict(params_by_rule.get(rule.id, {}))
    p.update(overrides)
    # Backward-compatible master sliders/session params. Canonical GL36 ε
    # parameters remain independently adjustable; a changed legacy master
    # intentionally updates each related sensor error unless that specific
    # canonical ε was also explicitly changed.
    if "mix_tol" in overrides:
        for key in ("eps_mat", "eps_rat", "eps_oat", "eps_sat", "eps_ccet", "eps_cclt", "eps_hcet", "eps_hclt"):
            if key in p and key not in overrides:
                p[key] = float(overrides["mix_tol"])
    if "supply_tol" in overrides and "eps_sat" in p and "eps_sat" not in overrides:
        p["eps_sat"] = float(overrides["supply_tol"])
    aliases = {
        "duct_static_err": "eps_dsp",
        "airflow_err": "eps_airflow",
        "oat_rat_delta_min": "delta_t_min",
        "sat_err": "eps_sat",
    }
    for legacy, canonical in aliases.items():
        if legacy in overrides and canonical in p and canonical not in overrides:
            p[canonical] = float(overrides[legacy])
    if "fan_hi" in overrides and "eps_vfd_spd" in p and "eps_vfd_spd" not in overrides:
        p["eps_vfd_spd"] = max(0.0, 1.0 - float(overrides["fan_hi"]))
    return p


def _ctx_from_df(df: pd.DataFrame, equipment_id: str, equipment_type: str) -> tuple[str, str, str]:
    site_id = str(df.attrs.get("site_id", ""))
    building_id = str(df.attrs.get("building_id", ""))
    eq_type = str(df.attrs.get("equipment_type", equipment_type))
    return site_id, building_id, eq_type


def run_cookbook_rule(
    rule: cb.CookbookRule,
    df: pd.DataFrame,
    *,
    equipment_id: str,
    equipment_kind: str,
    poll_seconds: float,
    params_by_rule: dict[str, dict] | None = None,
    weather: pd.DataFrame | None = None,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "",
    require_operational_gates: bool = True,
    skip_weather_merge: bool = False,
) -> RuleResult:
    params_by_rule = params_by_rule or {}
    eq_type = equipment_type or equipment_type_from_id(equipment_id)
    sid, bid, _ = _ctx_from_df(df, equipment_id, eq_type)
    sid = site_id or sid
    bid = building_id or bid

    if equipment_kind != "unknown" and equipment_kind not in rule.equipment_kinds:
        return not_applicable(
            rule.id,
            equipment_id,
            equipment_kind,
            site_id=sid,
            building_id=bid,
            equipment_type=eq_type,
        )

    from app.weather_resolver import inject_oa_t_for_physics, weather_source_metrics

    if skip_weather_merge:
        d = df
    else:
        d = merge_weather(df, weather)
        # OAT-METEO needs both real sources — never inject web into oa_t for the compare.
        if rule.id != "OAT-METEO":
            d = inject_oa_t_for_physics(d)
    # Fingerprint after params resolve; still stamp skips that happen after params exist.
    missing = _missing_roles(rule, d)
    if missing:
        notes = ""
        if rule.id == "OAT-METEO":
            notes = "SKIPPED — OAT-METEO requires both BAS oa_t and web wx_oa_t: " + "; ".join(missing)
        pre_params = _params_for_rule(rule, params_by_rule)
        return skipped(
            rule.id,
            equipment_id,
            missing,
            notes=notes,
            site_id=sid,
            building_id=bid,
            equipment_type=eq_type,
            params_fingerprint=params_fingerprint(
                rule.id, pre_params, gates_on=require_operational_gates
            ),
        )

    params = _params_for_rule(rule, params_by_rule)
    confirm_s = _confirm_seconds(rule, params)
    fp = params_fingerprint(rule.id, params, gates_on=require_operational_gates)
    wx_ok = weather_available(d)
    spec = RULE_GATES.get(rule.id)

    try:
        active, gate_meta = resolve_operational_mask(
            d,
            rule.id,
            poll_seconds=poll_seconds,
            params=params,
            gate_enabled=require_operational_gates,
        )
        if should_skip_equipment_off(gate_meta, params, spec):
            return equipment_off(
                rule.id,
                equipment_id,
                site_id=sid,
                building_id=bid,
                equipment_type=eq_type,
                metrics={**gate_meta, **weather_source_metrics(d)},
                notes=(
                    f"SKIPPED_EQUIPMENT_OFF — operational gate '{gate_meta.get('gate_kind')}' "
                    f"via {gate_meta.get('gate_source')}: no proven-on samples."
                ),
                params_fingerprint=fp,
            )

        if rule.id == "ECON-3":
            raw = econ3_compute(d, params, poll_seconds, wx_ok)
        elif rule.id == "OAT-METEO":
            # Compare real BAS vs web — restore bas_oa_t into oa_t if needed
            if "bas-outside-air-temp" in d.columns and d["bas-outside-air-temp"].notna().any():
                d = d.copy()
                d["outside-air-temp"] = d["bas-outside-air-temp"]
            raw = rule.compute(d, params, poll_seconds)
        else:
            raw = rule.compute(d, params, poll_seconds)
        raw = raw.reindex(d.index).fillna(False).astype(bool)
        metrics: dict[str, Any] = {**dict(gate_meta), **weather_source_metrics(d)}
        use_active = bool(gate_meta.get("gate_applied"))
        if rule.id == "ECON-3":
            metrics["weather_gate"] = d.attrs.get("econ3_weather_source", "")
            metrics["weather_gate_detail"] = (
                "web dewpoint/RH" if d.attrs.get("econ3_weather_source") in {"web_dewpoint", "web_db_rh_magnus"} else "missing"
            )
        if rule.id == "ECON-7":
            metrics["weather_gate"] = d.attrs.get("econ7_weather_source", "")
            metrics["weather_gate_detail"] = (
                "web dewpoint/RH" if d.attrs.get("econ7_weather_source") in {"web_dewpoint", "web_db_rh_magnus"} else "missing"
            )
            if d.attrs.get("econ7_proof"):
                metrics["cooling_proof"] = d.attrs.get("econ7_proof")
        if rule.id in {"SV-RATE", "SV-SLEW"}:
            from app.rules.sensor_rate import RATEABLE_ROLES

            metrics["sensors_checked"] = [r for r in RATEABLE_ROLES if r in d.columns and d[r].notna().any()]
            metrics["sv_rate_evidence"] = list(d.attrs.get("sv_rate_evidence") or [])
            metrics["sv_rate_state_meta"] = dict(d.attrs.get("sv_rate_state_meta") or {})
        elif rule.sensor_sweep:
            metrics["sensors_checked"] = [r for r in cb.SWEEP_SENSOR_ROLES if r in d.columns]
            # Confirm each per-role raw mask so UI itemization matches confirmed faults
            raw_masks = d.attrs.get("sv_sweep_masks") or {}
            active_for_roles = active if use_active else None
            confirmed_evidence = []
            role_confirmed: dict[str, pd.Series] = {}
            for role, role_raw in raw_masks.items():
                rr = role_raw.reindex(d.index).fillna(False).astype(bool)
                if active_for_roles is not None:
                    rr = rr & active_for_roles.reindex(d.index).fillna(False).astype(bool)
                role_conf = confirm_fault(rr, poll_seconds=poll_seconds, confirm_seconds=confirm_s)
                role_confirmed[role] = role_conf
                n_fault = int(role_conf.sum())
                first_ts = last_ts = None
                if n_fault and isinstance(role_conf.index, pd.DatetimeIndex):
                    idx = role_conf.index[role_conf]
                    first_ts, last_ts = str(idx[0]), str(idx[-1])
                confirmed_evidence.append(
                    {
                        "role": role,
                        "sensor_type": cb.sensor_type_for_role(role),
                        "fault_samples": n_fault,
                        "fault_hours": round(hours_true(role_conf, poll_seconds), 3) if n_fault else 0.0,
                        "first_fault_timestamp": first_ts,
                        "last_fault_timestamp": last_ts,
                        "faulted": n_fault > 0,
                    }
                )
            metrics["sv_sweep_evidence"] = confirmed_evidence
            metrics["sv_sweep_confirmed_roles"] = {
                role: role_confirmed[role].astype(int) for role in role_confirmed
            }
        if rule.control_output_sweep:
            metrics["outputs_checked"] = [r for r in cb.CONTROL_OUTPUT_ROLES if r in d.columns]
        if d.attrs.get("oa_t_injected_from"):
            metrics["oa_t_injected_from"] = d.attrs["oa_t_injected_from"]
        for attr_key, metric_key in (
            ("mech_oat1_weather_source", "weather_source"),
            ("mech_oat1_proof", "mech_proof"),
            ("econ6_weather_source", "weather_source"),
            ("chw_noload_proof", "mech_proof"),
        ):
            if d.attrs.get(attr_key):
                metrics[metric_key] = d.attrs[attr_key]
        return finalize_result(
            rule.id,
            equipment_id,
            raw,
            poll_seconds,
            confirm_s,
            site_id=sid,
            building_id=bid,
            equipment_type=eq_type,
            metrics=metrics,
            plot_series=_plot_series_for_rule(rule, d),
            active_mask=active if use_active else None,
            params_fingerprint=fp,
        )
    except Exception as exc:
        return error_result(
            rule.id,
            equipment_id,
            exc,
            site_id=sid,
            building_id=bid,
            equipment_type=eq_type,
            params_fingerprint=fp,
        )


def run_all_cookbook_rules(
    df: pd.DataFrame,
    *,
    equipment_id: str,
    poll_seconds: float,
    params_by_rule: dict[str, dict] | None = None,
    weather: pd.DataFrame | None = None,
    site_id: str = "",
    building_id: str = "",
    equipment_type: str = "",
    require_operational_gates: bool = True,
) -> list[RuleResult]:
    from app.weather_resolver import inject_oa_t_for_physics

    eq_type = resolve_equipment_type(
        equipment_id, df=df, explicit=equipment_type or None
    )
    kind = infer_equipment_kind(equipment_id, equipment_type=eq_type, df=df)
    # Merge weather once per equipment (not once per rule).
    d_merged = merge_weather(df, weather)
    d_physics = inject_oa_t_for_physics(d_merged)
    return [
        run_cookbook_rule(
            rule,
            d_merged if rule.id == "OAT-METEO" else d_physics,
            equipment_id=equipment_id,
            equipment_kind=kind,
            poll_seconds=poll_seconds,
            params_by_rule=params_by_rule,
            weather=None,
            site_id=site_id,
            building_id=building_id,
            equipment_type=eq_type,
            require_operational_gates=require_operational_gates,
            skip_weather_merge=True,
        )
        for rule in RULES  # canonical + CUSTOM-* (assigned below via active_rules)
    ]


def run_batch(
    equipment_frames: dict[str, pd.DataFrame],
    *,
    params_by_rule: dict[str, dict] | None = None,
    weather: pd.DataFrame | None = None,
    equipment_filter: set[str] | None = None,
    building_filter: str | None = None,
    site_filter: str | None = None,
    vav_to_ahu: dict[str, str] | None = None,
) -> list[RuleResult]:
    """Run all cookbook rules for each equipment in scope — no silent omission."""
    from app.load_satisfaction import aggregate_load_satisfaction
    from app.topology_enrich import enrich_frames_with_ahu_feeds, stamp_feed_attrs

    # Optional topology: copy parent AHU SAT onto VAV frames as ahu_sat
    rm: dict = {}
    for eq_id, raw_df in equipment_frames.items():
        block = (raw_df.attrs.get("_role_map") or {}).get(eq_id)
        if isinstance(block, dict):
            rm[eq_id] = block
        # Also accept flat attrs role_map
        if not block and isinstance(raw_df.attrs.get("_role_map"), dict):
            rm.update({k: v for k, v in raw_df.attrs["_role_map"].items() if isinstance(v, dict)})

    if vav_to_ahu:
        stamp_feed_attrs(equipment_frames, vav_to_ahu)
        enrich_frames_with_ahu_feeds(equipment_frames, vav_to_ahu, role_map=rm)

    # Comfort band from CHW-NOLOAD / VAV-1 params when present
    comfort_lo = 70.0
    comfort_hi = 75.0
    sat_band = 2.0
    pbr = params_by_rule or {}
    for rid in ("CHW-NOLOAD-1", "VAV-1", "SCHED-1"):
        block = pbr.get(rid) or {}
        if "comfort_low_f" in block:
            comfort_lo = float(block["comfort_low_f"])
        if "comfort_high_f" in block:
            comfort_hi = float(block["comfort_high_f"])
        if "zone_lo" in block:
            comfort_lo = float(block["zone_lo"])
        if "zone_hi" in block:
            comfort_hi = float(block["zone_hi"])
        if "sat_band_f" in block:
            sat_band = float(block["sat_band_f"])
    aggregate_load_satisfaction(
        equipment_frames,
        rm,
        comfort_low_f=comfort_lo,
        comfort_high_f=comfort_hi,
        sat_band_f=sat_band,
    )

    results: list[RuleResult] = []
    for eq_id, raw_df in sorted(equipment_frames.items()):
        if equipment_filter is not None and eq_id not in equipment_filter:
            continue
        sid = str(raw_df.attrs.get("site_id", ""))
        bid = str(raw_df.attrs.get("building_id", ""))
        if site_filter and sid and sid != site_filter:
            continue
        if building_filter and bid and bid != building_filter:
            continue
        from app.role_map import apply_role_map

        role_map = raw_df.attrs.get("_role_map") or {}
        mapped = apply_role_map(raw_df, eq_id, role_map)
        mapped.attrs.update(raw_df.attrs)
        mapped.attrs["equipment_id"] = eq_id
        # Preserve topology-enriched ahu_sat if apply_role_map dropped it
        if "ahu-discharge-air-temp" in raw_df.columns and "ahu-discharge-air-temp" not in mapped.columns:
            mapped["ahu-discharge-air-temp"] = raw_df["ahu-discharge-air-temp"]
        poll = float(raw_df.attrs.get("poll_seconds") or 300.0)
        eq_type = resolve_equipment_type(eq_id, df=raw_df, role_map=role_map)
        results.extend(
            run_all_cookbook_rules(
                mapped,
                equipment_id=eq_id,
                poll_seconds=poll,
                params_by_rule=params_by_rule,
                weather=weather,
                site_id=sid,
                building_id=bid,
                equipment_type=eq_type,
            )
        )
    return results


from app.rules.custom_registry import active_rules, active_rules_by_id

RULES = active_rules()
RULES_BY_ID = active_rules_by_id()
catalog = cb.catalog
