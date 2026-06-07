"""Deterministic root-cause hints for multi-fault dashboards (BRICK feeds + schedules).

Feeds Ollama building insight — not a replacement for Arrow FDD rules.
"""

from __future__ import annotations

from typing import Any

ZONE_FAULT_CODES = frozenset({"VAV-C", "VAV-A", "VAV-B", "VAV-D"})
MECHANICAL_TYPES = frozenset(
    {
        "AHU",
        "Air_Handler",
        "Chiller",
        "Boiler",
        "Pump",
        "Fan",
        "RTU",
        "DOAS",
        "CRAH",
        "VAV",
    }
)


def _zone_fault_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        code = str(alert.get("code") or "").strip().upper()
        title = str(alert.get("title") or "").lower()
        if code in ZONE_FAULT_CODES or "zone" in title or "zn-t" in title or "zn_t" in title:
            out.append(alert)
    return out


def build_root_cause_hints(
    alerts: list[dict[str, Any]],
    *,
    site_id: str | None = None,
    zone_snapshot: dict[str, Any] | None = None,
    brick_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Suggest upstream mechanical suspects when many zone faults cluster."""
    zone_faults = _zone_fault_alerts(alerts)
    struggling = (zone_snapshot or {}).get("struggling_zones") or []
    systems = (zone_snapshot or {}).get("systems") or []
    research = (zone_snapshot or {}).get("research") or {}
    fan_schedule = (zone_snapshot or {}).get("fan_schedule") or {}

    hints: list[str] = []
    pattern: str | None = None

    n_zone = max(len(zone_faults), len(struggling))
    if n_zone >= 2:
        pattern = "multi_zone_fault"
        ahu_names = sorted(
            {str(s.get("ahu_name") or "").strip() for s in systems if str(s.get("ahu_name") or "").strip()}
        )
        if ahu_names:
            hints.append(
                f"{n_zone} zone temperature fault(s) — shared upstream air handlers: {', '.join(ahu_names[:4])}. "
                "Check AHU supply temp, discharge static, economizer, and whether one AHU feeds all affected zones."
            )
        else:
            hints.append(
                f"{n_zone} zone temperature fault(s) site-wide — add brick:feeds (AHU→VAV) on the data model "
                "to trace a single mechanical root cause."
            )

        chains = (brick_graph or {}).get("feeds_chains") or []
        mech_chains = [
            c
            for c in chains
            if isinstance(c, str)
            and any(t.lower() in c.lower() for t in ("chiller", "boiler", "pump", "plant", "ahu", "doas", "rtu"))
        ]
        if mech_chains:
            hints.append(f"BRICK feeds trace: {mech_chains[0]}" + (f"; {mech_chains[1]}" if len(mech_chains) > 1 else ""))

    overnight_fan = fan_schedule.get("overnight_fan_on_minutes")
    weekday_stop = fan_schedule.get("weekday_typical_stop_hour_local")
    if overnight_fan and int(overnight_fan) > 30:
        satisfied = research.get("zones_satisfied_unoccupied_count") or research.get("minimal_setback_zone_count")
        if satisfied is not None and int(satisfied) >= 1:
            pattern = pattern or "after_hours_fan"
            hints.append(
                f"Supply fan ran ~{int(overnight_fan)} min overnight while zones appear satisfied/setback — "
                "review schedule vs mechanical runtime (possible simultaneous heating/cooling or stuck command)."
            )
        else:
            hints.append(
                f"Supply fan overnight runtime ~{int(overnight_fan)} min — verify schedule and after-hours overrides."
            )

    stale_sensors = int(research.get("suspicious_sensors_count") or research.get("stale_sensor_count") or 0)
    if stale_sensors and n_zone >= 2:
        hints.append(
            f"{stale_sensors} zone sensor(s) stale or FDD-flagged — fix comms before blaming mechanical plant."
        )

    return {
        "site_id": site_id,
        "pattern": pattern,
        "zone_fault_count": len(zone_faults),
        "struggling_zone_count": len(struggling),
        "hints": hints[:6],
        "feeds_chain_sample": ((brick_graph or {}).get("feeds_chains") or [])[:6],
    }
