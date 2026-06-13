"""Template analyst narratives for RCx DOCX (no external AI required)."""

from __future__ import annotations

from typing import Any


def build_chart_narrative(
    *,
    chart_id: str,
    title: str,
    stats: dict[str, Any],
    fault_summary: dict[str, Any] | None = None,
) -> str:
    """Plain-language paragraph akin to legacy OpenFDD FC1 report insights."""
    fs = fault_summary or {}
    active = int(fs.get("active_faults") or 0)
    fault_h = float(stats.get("fault_hours") or 0)
    fault_pct = float(stats.get("fault_percent") or 0)
    hours = float(stats.get("total_hours") or 0)

    if chart_id == "ahu_duct_static_vs_setpoint":
        intro = (
            "This chart compares duct static pressure to its setpoint while the supply fan modulates. "
            "A variable-frequency drive (VFD) raises fan speed to hold pressure in the duct; when the fan "
            "runs near maximum speed but pressure stays below setpoint, the AHU may be airflow-limited "
            "(filters, belt, vane, or undersized fan)."
        )
        if fault_pct > 5 or active > 0:
            body = (
                f"Fault overlays or analytics cover about {fault_pct:.1f}% of the {hours:.0f}-hour window "
                f"({fault_h:.1f} h). Review filters, belt tension, and static pressure reset — a fixed "
                "high setpoint with a fan pinned near 100% often wastes fan energy."
            )
        else:
            body = (
                "Fault activity is low in this window; duct static appears generally maintained. "
                "If the setpoint trace is flat, consider a duct static pressure reset schedule to trim fan energy."
            )
        return f"{intro} {body}"

    if chart_id == "ahu_sat_vs_setpoint":
        intro = (
            "Supply air temperature (SAT) should track its discharge setpoint when the AHU is conditioning. "
            "Large sustained gaps while valves or compressors modulate can indicate sensor, coil, or sequencing issues."
        )
        if fault_pct > 3:
            body = f"Fault flags appear for roughly {fault_pct:.1f}% of the period — prioritize SAT sensor validation and coil valve stroke tests."
        else:
            body = "No significant fault overlap in this window; SAT tracking looks reasonable at this resolution."
        return f"{intro} {body}"

    if chart_id == "vav_zone_temp":
        intro = (
            "Zone temperature is compared to heating and cooling setpoints at the VAV terminal. "
            "Chronic deviation with damper or reheat hunting can drive simultaneous heating and cooling upstream."
        )
        if fault_pct > 3:
            body = f"About {fault_pct:.1f}% of samples overlap FDD flags — inspect the worst zones for stuck dampers, reheat leaks, or bad zone sensors."
        else:
            body = "Zone comfort faults are sparse in this lookback; continue monitoring rogue zones that drive AHU reset."
        return f"{intro} {body}"

    if chart_id.startswith("custom_"):
        intro = f"Custom trend for selected BACnet point(s): {title}."
        if fault_pct > 0:
            body = f"FDD overlays account for ~{fault_pct:.1f}% of the window ({fault_h:.1f} h)."
        else:
            body = "No fault overlays on this custom series for the selected rules."
        return f"{intro} {body}"

    # Bar / analytics charts
    if "fault_hours" in chart_id:
        return (
            f"Fault-hour distribution for the {hours:.0f}-hour report window. "
            f"{active} active fault(s) were reported on the Edge. "
            "Use this chart to prioritize equipment with the longest elapsed fault time before field investigation."
        )

    return (
        f"Trend analysis for {title} over ~{hours:.0f} hours. "
        f"Active faults on Edge: {active}. "
        "Overlay bands (when enabled) show when FDD rules flagged samples during this period."
    )
