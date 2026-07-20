"""Streamlit RCx / multi-equipment plots tab — family-scoped presets, lazy heavy work."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.charts import (
    energy_degree_day_scatter,
    monthly_energy_bar,
    multi_equipment_box,
    multi_equipment_timeseries,
    oat_scatter,
    plotly_config,
)
from app.metering import build_meter_monthly_table, meter_scatter_frame
from app.occupancy import OccupancySchedule
from app.rcx_plots import (
    PRESETS,
    cohort_wants_fan_slices,
    collect_oat_scatter,
    collect_role_series,
    collect_status_series,
    fan_mode_summary_bundle,
    outlier_equipment_ids,
    preset_by_id,
    presets_for_family,
    series_summary_stats,
    zone_comfort_fail_ranking,
)
from app.reports import to_csv_bytes
from app.unit_system import convert_series


def _convert_map(series_map: dict[str, pd.Series], role: str, system: str) -> tuple[dict[str, pd.Series], str]:
    out: dict[str, pd.Series] = {}
    unit = ""
    for eq_id, s in series_map.items():
        conv, unit = convert_series(role, s, system)  # type: ignore[arg-type]
        out[eq_id] = conv
    return out, unit


def _render_summary_stats(
    *,
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    role: str,
    equipment_types: tuple[str, ...] | None,
    chart_series_map: dict[str, pd.Series],
    outlier_z: float,
    unit_system: str,
    key_prefix: str,
) -> None:
    """Summary tables: All / operating on / off for air-side cohorts when proof exists."""
    chart_stats = (
        series_summary_stats(chart_series_map, outlier_z=outlier_z) if chart_series_map else pd.DataFrame()
    )
    if chart_stats.empty and not cohort_wants_fan_slices(equipment_types):
        return

    st.markdown("##### Summary statistics")
    if not cohort_wants_fan_slices(equipment_types):
        if chart_stats.empty:
            return
        st.dataframe(chart_stats, hide_index=True, width="stretch", height=min(360, 80 + 28 * len(chart_stats)))
        st.download_button(
            "Download summary CSV",
            to_csv_bytes(chart_stats),
            "rcx_summary_stats.csv",
            key=f"{key_prefix}_dl_stats",
        )
        return

    # Reuse fan_mode_summary_bundle once (avoid 3× collect + convert loops).
    tables, proof_cap = fan_mode_summary_bundle(
        frames,
        role_map,
        role=role,
        equipment_types=equipment_types,
        outlier_z=outlier_z,
    )
    # Unit-convert means for display when metric — rebuild lightly from chart map for "all"
    display_tables = dict(tables)
    if unit_system == "metric" and chart_series_map:
        sm_all, _ = _convert_map(chart_series_map, role, unit_system)
        display_tables["all"] = series_summary_stats(sm_all, outlier_z=outlier_z)

    st.caption(proof_cap)
    tab_all, tab_on, tab_off = st.tabs(["All data", "Fan / air on", "Fan / air off"])
    labels = {
        "all": ("All timestamps", tab_all),
        "on": ("Operating (fan proven on or VAV airflow active)", tab_on),
        "off": ("Off / inactive periods", tab_off),
    }
    for mode_key, (blurb, tab) in labels.items():
        with tab:
            st.caption(blurb)
            stats = display_tables.get(mode_key, pd.DataFrame())
            if stats.empty:
                st.info("No rows for this slice — check mapping or operating proof.")
            else:
                n_out = int(stats["outlier"].sum()) if "outlier" in stats.columns else 0
                st.caption(f"{len(stats)} equipment · {n_out} outlier(s) at z≥{outlier_z:g}")
                st.dataframe(
                    stats, hide_index=True, width="stretch", height=min(360, 80 + 28 * len(stats))
                )
                st.download_button(
                    f"Download {mode_key} summary CSV",
                    to_csv_bytes(stats),
                    f"rcx_summary_stats_{mode_key}.csv",
                    key=f"{key_prefix}_dl_stats_{mode_key}",
                )


def render_rcx_plots_tab(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None,
    unit_system: str = "imperial",
    occupancy_schedule: dict | OccupancySchedule | None = None,
    zone_lo_f: float = 70.0,
    zone_hi_f: float = 75.0,
) -> None:
    st.subheader("RCx plots")
    st.caption(
        "Pick a **mechanical family** first (Zones / AHU / Boiler / Chiller / Heat pump / Metering / Weather), "
        "then one preset when charts exist for that family. "
        "Word report: download the Generic RCx template from **Overview**."
    )

    schedule = (
        occupancy_schedule
        if isinstance(occupancy_schedule, OccupancySchedule)
        else OccupancySchedule.from_dict(occupancy_schedule)
    )
    outlier_z = st.slider("Outlier z-score (mean vs cohort)", 1.5, 4.0, 2.5, 0.1, key="rcx_z")

    from app.docx_report import rcx_families

    # --- Family → preset (AHU list never includes chiller/boiler) ---
    family = st.selectbox(
        "Mechanical family",
        list(rcx_families()),
        key="rcx_family",
        help="Scopes the plot list so plant reset charts are not mixed under AHU. "
        "Heat pump / Weather may have empty charts until presets exist.",
    )

    # --- Lazy coverage (was scanning every preset × every equipment on each run) ---
    show_cov = st.checkbox(
        "Show preset coverage diagnostics (slow on large packages)",
        value=False,
        key="rcx_show_coverage",
    )
    if show_cov:
        from app.rcx_plots import rcx_preset_coverage

        with st.spinner("Computing RCx preset coverage…"):
            cov = rcx_preset_coverage(
                frames,
                role_map,
                weather=weather,
                outlier_z=outlier_z,
                schedule=schedule,
                comfort_low_f=zone_lo_f,
                comfort_high_f=zone_hi_f,
            )
        st.dataframe(cov, hide_index=True, width="stretch", height=320)
        nonempty = int((cov["row_count"] > 0).sum()) if not cov.empty else 0
        st.caption(f"{nonempty}/{len(cov)} presets have data")
        st.download_button(
            "Download rcx_preset_coverage.csv",
            to_csv_bytes(cov),
            "rcx_preset_coverage.csv",
            key="dl_rcx_coverage",
        )
    family_presets = presets_for_family(family)
    if not family_presets:
        st.info(
            f"No RCx chart presets in **{family}** yet — use the Word template above "
            "(paste Plotly screenshots from FDD Plots / Overview as needed)."
        )
        return

    def _label(pid: str) -> str:
        p = preset_by_id(pid)
        return p.title if p else pid

    pid = st.selectbox(
        "Plot",
        [p.id for p in family_presets],
        format_func=_label,
        key=f"rcx_preset_{family}",
    )
    preset = preset_by_id(pid)
    assert preset is not None
    st.caption(preset.description)

    # Fan (air) / pump (plant) operating filter — Streamlit reruns on toggle (instant).
    plant_families = {"Boiler / HW", "Chiller / CHW / tower"}
    op_kind = "pump" if family in plant_families else "fan"
    filter_label = (
        "Filter to pump proven on" if op_kind == "pump" else "Filter to fan / air proven on"
    )
    operating_on = False
    overlay_status = False
    if preset.chart != "metering":
        c_filter, c_overlay = st.columns(2)
        with c_filter:
            operating_on = st.checkbox(
                filter_label,
                value=True,
                key=f"rcx_op_on_{family}_{preset.id}",
                help=(
                    "When checked, keeps only samples while the fan (AHU/VAV) or hydronic pump "
                    "(boiler/chiller/tower) is proven on — cleans reset scatters and overlays. "
                    "Uncheck to show all timestamps."
                ),
            )
        if preset.chart in {"timeseries", "ranking"}:
            with c_overlay:
                overlay_status = st.checkbox(
                    "Overlay motor / fan status (0/1)",
                    value=False,
                    key=f"rcx_status_overlay_{family}_{preset.id}",
                    help=(
                        "Adds a dotted 0/1 step line per equipment on a right-hand axis "
                        "(fan/pump status, cmd, or VAV airflow proof) so run status reads "
                        "alongside the plotted values."
                    ),
                )

    role = preset.role
    chart_kind = preset.chart
    title = preset.title
    equipment_types = preset.equipment_types
    series_map: dict[str, pd.Series] = {}
    long_df = pd.DataFrame()
    y_title = ""
    x_title = "Web dry-bulb °F"

    if chart_kind == "ranking":
        rank = zone_comfort_fail_ranking(
            frames,
            role_map,
            schedule=schedule,
            comfort_low_f=zone_lo_f,
            comfort_high_f=zone_hi_f,
            equipment_types=equipment_types,
            outlier_z=outlier_z,
        )
        st.markdown("##### Zone comfort fail ranking")
        st.caption(
            f"Occupied hours only (Overview schedule). Band **{zone_lo_f:g}–{zone_hi_f:g} °F** "
            f"(same as VAV-1 / SCHED-1). Worst % outside first."
        )
        if rank.empty:
            st.info("No VAV `zone_t` samples during occupied hours — check mapping and schedule.")
        else:
            from app.charts import vav_comfort_donut

            n_out = int(rank["outlier"].sum()) if "outlier" in rank.columns else 0
            st.caption(f"{len(rank)} zones · {n_out} outlier(s) by fail-% vs cohort")
            c_tbl, c_pie = st.columns([1.6, 1.0])
            with c_tbl:
                st.dataframe(rank, hide_index=True, width="stretch", height=min(480, 80 + 28 * len(rank)))
            with c_pie:
                pie = vav_comfort_donut(rank)
                if pie is not None:
                    st.plotly_chart(
                        pie,
                        width="stretch",
                        config=plotly_config(filename="rcx_zone_comfort_donut"),
                        key="rcx_zone_comfort_donut",
                    )
                zone_pick = st.selectbox(
                    "Per-zone donut",
                    ["(all zones)"] + list(rank["equipment_id"].astype(str)),
                    key="rcx_zone_donut_pick",
                )
                if zone_pick != "(all zones)":
                    one = rank[rank["equipment_id"].astype(str) == zone_pick]
                    one_pie = vav_comfort_donut(one, title=f"{zone_pick} — comfort band")
                    if one_pie is not None:
                        st.plotly_chart(
                            one_pie,
                            width="stretch",
                            config=plotly_config(filename=f"rcx_zone_donut_{zone_pick}"),
                            key=f"rcx_zone_donut_{zone_pick}",
                        )
            st.download_button(
                "Download zone comfort ranking CSV",
                to_csv_bytes(rank),
                "rcx_zone_comfort_ranking.csv",
                key="dl_rcx_zone_rank",
            )
            worst_ids = list(rank["equipment_id"].astype(str).head(12))
            series_map = collect_role_series(
                frames,
                role_map,
                role="zone-air-temp",
                equipment_types=equipment_types,
                equipment_ids=worst_ids,
                fan_mode="on" if operating_on else "all",
            )
            series_map, y_title = _convert_map(series_map, "zone-air-temp", unit_system)
            outliers = (
                set(rank.loc[rank["outlier"], "equipment_id"].astype(str))
                if "outlier" in rank.columns
                else set()
            )
            status_map = (
                collect_status_series(
                    frames,
                    role_map,
                    equipment_types=equipment_types,
                    equipment_ids=worst_ids,
                    kind=op_kind,
                )
                if overlay_status
                else None
            )
            fig = multi_equipment_timeseries(
                series_map,
                title=f"Worst zones — space temp (top {len(worst_ids)})",
                y_title=y_title or "zone-air-temp",
                outlier_ids=outliers,
                status_map=status_map,
            )
            if fig is not None:
                st.plotly_chart(
                    fig,
                    width="stretch",
                    config=plotly_config(filename="rcx_zone_comfort_worst"),
                    key="rcx_zone_rank_ts",
                )
        return

    if chart_kind == "metering":
        kind = "electric" if preset.id == "meter_elec_cdd" else "gas"
        energy_col = "kwh" if kind == "electric" else "gas_qty"
        dd_name = "CDD" if kind == "electric" else "HDD"
        monthly_df, stats_df, reason = build_meter_monthly_table(
            frames,
            role_map,
            kind=kind,  # type: ignore[arg-type]
            weather=weather,
            equipment_types=preset.equipment_types,
        )
        st.markdown(f"##### Metering · {'electric' if kind == 'electric' else 'natural gas'}")
        st.caption(
            f"Rate → monthly energy via sample intervals. "
            f"Scatter uses monthly total vs **{dd_name}** (base 65°F from web dry-bulb)."
        )
        if monthly_df.empty:
            st.info(reason or "No metering series — map `elec_power_kw` / `gas_flow` on METER (or plant) equipment.")
            return
        bar = monthly_energy_bar(
            monthly_df,
            energy_col=energy_col,
            title=title,
            y_title="kWh / month" if kind == "electric" else "Gas quantity / month",
        )
        if bar is not None:
            st.plotly_chart(
                bar,
                width="stretch",
                config=plotly_config(filename=f"rcx_{preset.id}_bar"),
                key=f"rcx_meter_bar_{preset.id}",
            )
        sc = meter_scatter_frame(monthly_df, kind=kind)  # type: ignore[arg-type]
        scat = energy_degree_day_scatter(
            sc,
            title=f"{'Electric kWh' if kind == 'electric' else 'Gas'} vs {dd_name}",
            x_title=f"{dd_name} (°F·day, base 65)",
            y_title="kWh / month" if kind == "electric" else "Gas / month",
        )
        if scat is None:
            st.warning(f"No {dd_name} points — load weather / web OAT for degree-day scatter.")
        else:
            st.plotly_chart(
                scat,
                width="stretch",
                config=plotly_config(filename=f"rcx_{preset.id}_scatter"),
                key=f"rcx_meter_scatter_{preset.id}",
            )
        st.markdown("##### Summary statistics")
        if not stats_df.empty:
            st.dataframe(stats_df, hide_index=True, width="stretch", height=min(360, 80 + 28 * len(stats_df)))
        st.dataframe(monthly_df, hide_index=True, width="stretch", height=min(360, 80 + 28 * len(monthly_df)))
        st.download_button(
            "Download monthly metering CSV",
            to_csv_bytes(monthly_df),
            f"rcx_{preset.id}_monthly.csv",
            key=f"dl_rcx_meter_{preset.id}",
        )
        return

    if chart_kind == "scatter_oat":
        x_pref = "wetbulb" if preset.id == "cw_reset_scatter" else "web"
        long_df = collect_oat_scatter(
            frames,
            role_map,
            y_role=preset.role,
            weather=weather,
            equipment_types=preset.equipment_types,
            x_prefer=x_pref,
            operating_on=operating_on,
            operating_kind=op_kind,
        )
        if unit_system == "metric" and not long_df.empty:
            long_df = long_df.copy()
            long_df["y"], y_title = convert_series(role, long_df["y"], "metric")
            long_df["oat"], _xu = convert_series("outside-air-temp", long_df["oat"], "metric")
            if "dry_bulb" in long_df.columns:
                long_df["dry_bulb"], _ = convert_series("outside-air-temp", long_df["dry_bulb"], "metric")
            x_title = "Web wet-bulb °C" if x_pref == "wetbulb" else "Web dry-bulb °C"
        else:
            y_title = role
            x_title = "Web wet-bulb °F" if x_pref == "wetbulb" else "Web dry-bulb °F"
            if preset.dry_bulb_ref:
                x_title = "Web wet-bulb °F (markers) · web dry-bulb ref (×)"

        fig = oat_scatter(
            long_df,
            title=title,
            x_title=x_title,
            y_title=y_title or role,
            dry_bulb_ref=bool(preset.dry_bulb_ref),
        )
        if fig is None:
            st.info("No scatter points — map plant leave temps and ensure weather/web OAT is loaded.")
        else:
            if preset.dry_bulb_ref:
                st.caption("Primary X = wet-bulb; × markers = same Y vs dry-bulb (approach reference).")
            # Key must be unique per preset — a shared key can leave the previous
            # preset's figure (e.g. tower wet-bulb axis) rendered after switching.
            st.plotly_chart(
                fig,
                width="stretch",
                config=plotly_config(filename=f"rcx_{preset.id}"),
                key=f"rcx_scatter_{preset.id}",
            )
            st.dataframe(long_df.head(2000), hide_index=True, width="stretch", height=220)
        return

    if preset.pair_return_role:
        # Supply / return / ΔT per device (e.g. CHW or CW temps). Kept in °F —
        # ΔT must not go through the °C offset conversion.
        from app.rcx_plots import collect_paired_temp_series

        series_map = collect_paired_temp_series(
            frames,
            role_map,
            supply_role=preset.role,
            return_role=preset.pair_return_role,
            equipment_types=preset.equipment_types,
            operating="on" if operating_on else "all",
            operating_kind=op_kind,
        )
        y_title = "°F (ΔT = return − supply)"
        if not series_map:
            st.info(
                "No supply/return temperature series — map "
                f"`{preset.role}` and/or `{preset.pair_return_role}` on plant equipment."
            )
        elif not any(k.endswith("· ΔT") for k in series_map):
            st.caption(
                "ΔT traces appear when **both** supply and return temps are mapped on the same device."
            )
    elif op_kind == "pump" and operating_on:
        from app.rcx_plots import collect_role_series_pump_mode

        series_map = collect_role_series_pump_mode(
            frames,
            role_map,
            role=preset.role,
            equipment_types=preset.equipment_types,
            pump_mode="on",
        )
        series_map, y_title = _convert_map(series_map, role, unit_system)
    else:
        series_map = collect_role_series(
            frames,
            role_map,
            role=preset.role,
            equipment_types=preset.equipment_types,
            filter_fan_on=preset.filter_fan_on or operating_on,
            fan_mode="on" if operating_on else "all",
        )
        series_map, y_title = _convert_map(series_map, role, unit_system)

    if preset.overlay_role and series_map:
        # Companion role per equipment (e.g. duct static setpoint) — same unit family.
        overlay_map = collect_role_series(
            frames,
            role_map,
            role=preset.overlay_role,
            equipment_types=preset.equipment_types,
            equipment_ids=list(series_map.keys()),
        )
        overlay_map, _ = _convert_map(overlay_map, role, unit_system)
        for eq_id, s in overlay_map.items():
            series_map[f"{eq_id} · setpoint"] = s
        if not overlay_map:
            st.caption(f"No `{preset.overlay_role}` mapped — showing measured values only.")
    if operating_on or preset.filter_fan_on:
        proof = "pump" if op_kind == "pump" else "fan"
        st.info(
            f"Filtered to **{proof} proven on**. "
            + (
                "High, flat duct static while the fan runs often means a duct-static-pressure "
                "reset would save fan energy — compare with motor run-hours on Overview."
                if preset.filter_fan_on
                else "Uncheck the filter to include all timestamps."
            )
        )

    stats = series_summary_stats(series_map, outlier_z=outlier_z) if series_map else pd.DataFrame()
    outliers = outlier_equipment_ids(stats)

    if chart_kind == "box":
        fig = multi_equipment_box(series_map, title=title, y_title=y_title, outlier_ids=outliers)
        key = f"rcx_box_{preset.id}"
    else:
        # Paired/overlay presets label series "EQ · supply" etc — strip back to eq ids.
        base_ids = sorted({k.split(" · ")[0] for k in series_map})
        status_map = (
            collect_status_series(
                frames,
                role_map,
                equipment_types=equipment_types,
                equipment_ids=base_ids,
                kind=op_kind,
            )
            if overlay_status
            else None
        )
        fig = multi_equipment_timeseries(
            series_map, title=title, y_title=y_title, outlier_ids=outliers, status_map=status_map
        )
        key = f"rcx_ts_{preset.id}"
    if fig is None:
        st.info("No series for this preset — check role mapping / Data Model.")
    else:
        st.plotly_chart(fig, width="stretch", config=plotly_config(filename=f"rcx_{preset.id}"), key=key)

    _render_summary_stats(
        frames=frames,
        role_map=role_map,
        role=role,
        equipment_types=equipment_types,
        chart_series_map=series_map,
        outlier_z=outlier_z,
        unit_system=unit_system,
        key_prefix=f"rcx_{preset.id}",
    )

    with st.expander("Generic role picker (advanced)", expanded=False):
        st.caption("Optional — only runs when you expand this section.")
        g_role = st.text_input("Cookbook role to plot", value="zone-air-temp", key="rcx_generic_role")
        g_types = st.multiselect(
            "Equipment types (empty = all)",
            ["AHU", "VAV", "CHW_PLANT", "CHILLER", "BOILER", "HP", "COOLING_TOWER", "METER", "WEATHER", "UNKNOWN"],
            default=[],
            key="rcx_types",
        )
        g_fan = st.checkbox("Filter chart to fan on", value=False, key="rcx_fan_on")
        g_kind = st.selectbox("Chart", ["timeseries", "box"], key="rcx_chart_kind")
        run_generic = st.checkbox("Render generic plot", value=False, key="rcx_generic_go")
        if not run_generic:
            return
        g_et = tuple(g_types) if g_types else None
        g_map = collect_role_series(
            frames,
            role_map,
            role=g_role.strip(),
            equipment_types=g_et,
            filter_fan_on=g_fan,
        )
        g_map, g_yt = _convert_map(g_map, g_role.strip(), unit_system)
        g_stats = series_summary_stats(g_map, outlier_z=outlier_z) if g_map else pd.DataFrame()
        g_out = outlier_equipment_ids(g_stats)
        if g_kind == "box":
            g_fig = multi_equipment_box(g_map, title=f"Generic · {g_role}", y_title=g_yt, outlier_ids=g_out)
        else:
            g_fig = multi_equipment_timeseries(
                g_map, title=f"Generic · {g_role}", y_title=g_yt, outlier_ids=g_out
            )
        if g_fig is not None:
            st.plotly_chart(g_fig, width="stretch", config=plotly_config(filename="rcx_generic"), key="rcx_generic")
        if not g_stats.empty:
            st.dataframe(g_stats, hide_index=True, width="stretch")
