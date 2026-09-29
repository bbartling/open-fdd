"""Family Zones comfort ranking is stamp/role membership, not equipment id text."""

from __future__ import annotations

import pandas as pd

from open_fdd.analytics.occupancy import OccupancySchedule
from open_fdd.analytics.rcx_plots import (
    ZONE_TERMINAL_TYPES,
    collect_role_series,
    zone_comfort_fail_ranking,
)


def _zone(temp: float) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 10:00", periods=4, freq="h", tz="America/Chicago")
    return pd.DataFrame({"zt": [temp, temp, 72.0, 72.0]}, index=idx)


def test_ranking_includes_stamped_zone_terminals_and_drops_wrong_stamp():
    frames = {
        "jci_vav_12": _zone(80.0),
        "AC_FCU": _zone(60.0),
        "HP_ZONE": _zone(72.0),
        "BB_1": _zone(90.0),
        "MON_1": _zone(71.0),
        "GENERIC_1": _zone(61.0),
        "ZONE_GHOST": _zone(50.0),
        "jci_vav_wrong": _zone(50.0),
    }
    role_map = {
        "jci_vav_12": {"equipment_type": "vav", "zone-air-temp": "zt"},
        "AC_FCU": {"equipment_type": "fcu", "zone-air-temp": "zt"},
        "HP_ZONE": {"equipment_type": "heatPump", "zone-air-temp": "zt"},
        "BB_1": {"equipment_type": "baseboard", "zone-air-temp": "zt"},
        "MON_1": {"equipment_type": "zone_other", "zone-air-temp": "zt"},
        "GENERIC_1": {"zone-air-temp": "zt"},
        "ZONE_GHOST": {"equipment_type": "ahu", "zone-air-temp": "zt"},
        "jci_vav_wrong": {"equipment_type": "ahu", "zone-air-temp": "zt"},
    }
    ranked = zone_comfort_fail_ranking(
        frames,
        role_map,
        schedule=OccupancySchedule(),
        comfort_low_f=70.0,
        comfort_high_f=75.0,
        equipment_types=ZONE_TERMINAL_TYPES,
    )
    ids = set(ranked["equipment_id"])
    assert ids == {"jci_vav_12", "AC_FCU", "HP_ZONE", "BB_1", "MON_1", "GENERIC_1"}
    assert "pct_in_comfort" in ranked.columns
    by_id = ranked.set_index("equipment_id")
    assert float(by_id.loc["HP_ZONE", "pct_in_comfort"]) == 100.0
    assert float(by_id.loc["BB_1", "pct_in_comfort"]) < 100.0
    assert list(ranked["equipment_id"]).index("BB_1") < list(ranked["equipment_id"]).index("HP_ZONE")


def test_zone_temp_series_uses_the_same_family():
    frames = {
        "AC_FCU": _zone(70.0),
        "ZONE_GHOST": _zone(70.0),
        "PLAIN": _zone(71.0),
    }
    role_map = {
        "AC_FCU": {"equipment_type": "fcu", "zone-air-temp": "zt"},
        "ZONE_GHOST": {"equipment_type": "ahu", "zone-air-temp": "zt"},
        "PLAIN": {"zone-air-temp": "zt"},
    }
    series = collect_role_series(
        frames,
        role_map,
        role="zone-air-temp",
        equipment_types=ZONE_TERMINAL_TYPES,
    )
    assert set(series) == {"AC_FCU", "PLAIN"}
