"""WattLab section — vibe20 Uploads → Fuel → Twin → ECMs inside open-fdd (OFDD-UI-V20).

Imports ``wattlab.studio.pages.*`` when the package is available (ui image / lab).
Otherwise shows an honest runner/workspace status instead of a fake Studio.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

WATTLab_PAGES = (
    "Uploads",
    "Fuel dashboard",
    "Twin / calibrate",
    "ECMs",
)


def _workspace_root() -> str | None:
    for key in ("WATTLAB_STUDIO_WORKSPACE", "WATTLAB_WORKSPACE", "OPENFDD_WATTLAB_WORKSPACE"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


def _try_import_page(mod_name: str):
    try:
        import importlib

        return importlib.import_module(f"wattlab.studio.pages.{mod_name}")
    except (ImportError, ModuleNotFoundError):
        # Missing package / page only — surface other import-time bugs to the UI.
        return None


def _render_ecm_monthly_pct_required_fallback(active: str) -> None:
    """Keep ECM monthly ±% chart slots when wattlab.studio.pages.ecms is unavailable.

    Prefers vibe20 ``render_required_monthly_pct_charts`` when importable; otherwise
    draws Plotly placeholders + the same agent checklist text.
    """
    st.markdown("#### Monthly dial ±% (E+ model vs actual bills)")
    st.caption(
        "Required on the ECM tab. Chart frames stay visible even without scorecard JSON."
    )
    try:
        from wattlab.studio.monthly_dial_chart import render_required_monthly_pct_charts

        render_required_monthly_pct_charts(
            [],
            key_prefix="ofdd_ecm_monthly_pm",
            twin_hint=active or None,
        )
        return
    except Exception:
        pass

    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    try:
        import plotly.graph_objects as go

        for fuel, title in (
            ("elec", "Electricity — monthly dial ±% (model vs bills)"),
            ("gas", "Natural gas — monthly dial ±% (model vs bills)"),
        ):
            fig = go.Figure(
                data=[
                    go.Bar(
                        x=months,
                        y=[0.0] * 12,
                        marker_color="#cbd5e0",
                        text=["—"] * 12,
                        textposition="outside",
                        name=f"{fuel} ±% (awaiting data)",
                    )
                ]
            )
            fig.add_annotation(
                text="Awaiting utility_bills.per_month — chart slot reserved",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.55,
                showarrow=False,
            )
            fig.update_layout(title=title, height=360, showlegend=False)
            st.plotly_chart(fig, width="stretch", key=f"ofdd_ecm_pm_fallback_{fuel}")
    except Exception as exc:
        st.info(f"Plotly unavailable for placeholder charts ({exc}).")

    st.warning(
        "**Please have AI agent render / attach:**\n"
        "- Publish `calibration_scorecard.json` with `utility_bills.per_month`\n"
        "- Elec months: `observed_kwh` + `modeled_kwh`/`simulated_kwh`\n"
        "- Gas months: `observed_therms` + `modeled_therms`/`simulated_therms`\n"
        "- Point ECM Twin at the calibrated `runs/…` folder\n"
        f"- Active site hint: `{active or '(none)'}`"
    )


def render_wattlab_section(*, building_id: str | None = None) -> None:
    """Main-section WattLab workspace (replaces Export-as-only-story)."""
    st.subheader("WattLab")
    active = (building_id or st.session_state.get("building_id") or st.session_state.get("active_site") or "").strip()
    if active:
        st.caption(f"Scoped to Active site `{active}`.")
    else:
        st.caption("No Active site — load a package and pick a Site first.")

    ws = _workspace_root()
    st.info(
        "WattLab hosts Fuel / Twin / ECMs. EnergyPlus runs need DinD + "
        "`energyplus-mcp-dev` (or an external runner) — never invented savings."
    )
    if ws:
        st.caption(f"Workspace: `{ws}`")
    else:
        st.warning(
            "No `WATTLAB_STUDIO_WORKSPACE` / `WATTLAB_WORKSPACE` mount — "
            "Twin/Fuel files will not resolve until the ui container shares `/data`."
        )

    page = st.radio(
        "WattLab workflow",
        list(WATTLab_PAGES),
        horizontal=True,
        key="wattlab_studio_page",
        help="Uploads → Fuel → Twin → ECMs (same spine as vibe20 Studio).",
    )

    profile: dict[str, Any] = {}
    if active:
        profile["building_id"] = active
        profile["site_id"] = active

    rendered = False
    if page == "Uploads":
        mod = _try_import_page("uploads")
        if mod and hasattr(mod, "render"):
            mod.render(profile=profile)
            rendered = True
    elif page == "Fuel dashboard":
        mod = _try_import_page("fuel_dashboard")
        if mod and hasattr(mod, "render"):
            mod.render(profile=profile)
            rendered = True
    elif page == "Twin / calibrate":
        mod = _try_import_page("twin_calibrate")
        if mod and hasattr(mod, "render"):
            mod.render(profile=profile)
            rendered = True
    elif page == "ECMs":
        mod = _try_import_page("ecms")
        if mod and hasattr(mod, "render"):
            mod.render(profile=profile)
            rendered = True
        else:
            _render_ecm_monthly_pct_required_fallback(active)

    if not rendered and page != "ECMs":
        st.warning(
            f"**{page}** UI requires the `wattlab` package in the openfdd-ui image "
            "(Option A embed). Until then use vibe20 Studio on `:8520` or install wattlab."
        )
        docker_sock = os.path.exists("/var/run/docker.sock")
        st.caption(
            f"Docker sock attached: {'yes' if docker_sock else 'no'} · "
            f"EnergyPlus MCP: set `OPENFDD_ENERGYPLUS_MCP=1` when runner is available."
        )
    elif not rendered and page == "ECMs":
        st.warning(
            "Full ECM compare UI needs the `wattlab` package — monthly ±% chart "
            "slots stay reserved below so the page never goes blank."
        )
        docker_sock = os.path.exists("/var/run/docker.sock")
        st.caption(
            f"Docker sock attached: {'yes' if docker_sock else 'no'} · "
            f"EnergyPlus MCP: set `OPENFDD_ENERGYPLUS_MCP=1` when runner is available."
        )

    with st.expander("Advanced — handoff / dump / agent-build", expanded=False):
        st.caption(
            "Dump zip and ECM package requests remain available for external pickup. "
            "They are not a substitute for the WattLab pages above."
        )
        try:
            from app.ui_wattlab_job import render_job_native_wattlab_handoff

            render_job_native_wattlab_handoff()
        except Exception as exc:
            st.caption(f"WattLab handoff panel unavailable: {exc}")
        try:
            from app.ui_ecm_job import render_ecm_agent_build_panel

            render_ecm_agent_build_panel()
        except Exception as exc:
            st.caption(f"ECM agent-build panel unavailable: {exc}")


__all__ = ["WATTLab_PAGES", "render_wattlab_section"]
