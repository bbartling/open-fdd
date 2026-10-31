"""FC6 OA-fraction threshold boundary at registry default MIN_CFM_DESIGN (5000 cfm → L/s)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

LPS_PER_CFM = 0.471947
DESIGN_CFM = 5000.0
DESIGN_L_S = DESIGN_CFM * LPS_PER_CFM
VAV_TOTAL_L_S = 10_000.0 * LPS_PER_CFM
PERC_OA_MIN = DESIGN_L_S / VAV_TOTAL_L_S
EPS_AIRFLOW = 0.15
POLL_SECONDS = 300.0
N_SAMPLES = 3
START = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Fc6BoundaryCase:
    case_id: str
    pct_oa_target: float
    expect_raw_fault: bool


def mat_for_pct_oa(pct_oa: float, *, rat: float = 25.0, oa: float = 15.0) -> float:
    return rat + pct_oa * (oa - rat)


def build_fc6_boundary_cases() -> list[Fc6BoundaryCase]:
    return [
        Fc6BoundaryCase("below", PERC_OA_MIN + EPS_AIRFLOW - 1e-6, False),
        Fc6BoundaryCase("equal", PERC_OA_MIN + EPS_AIRFLOW - 1e-12, False),
        Fc6BoundaryCase("above", PERC_OA_MIN + EPS_AIRFLOW + 1e-6, True),
    ]


def build_fc6_boundary_frame(case: Fc6BoundaryCase) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [START + timedelta(seconds=int(i * POLL_SECONDS)) for i in range(N_SAMPLES)],
        tz=timezone.utc,
    )
    mat = mat_for_pct_oa(case.pct_oa_target)
    data = {
        "mixed-air-temp": [mat] * N_SAMPLES,
        "return-air-temp": [25.0] * N_SAMPLES,
        "outside-air-temp": [15.0] * N_SAMPLES,
        "vav-total-airflow": [VAV_TOTAL_L_S] * N_SAMPLES,
        "fan-cmd": [1.0] * N_SAMPLES,
    }
    frame = pd.DataFrame(data, index=index)
    frame.attrs["equipment_type"] = "ahu"
    frame.attrs["equipment_id"] = "FC6_BOUNDARY"
    frame.attrs["storage_abi"] = "metric-c-v2"
    frame.attrs["role_units"] = {
        "mixed-air-temp": "°C",
        "return-air-temp": "°C",
        "outside-air-temp": "°C",
        "vav-total-airflow": "L/s",
        "fan-cmd": "percent",
    }
    return frame


def fc6_si_params(*, confirm_seconds: float = 0.0) -> dict[str, float]:
    return {
        "min_cfm_design": DESIGN_L_S,
        "eps_airflow": EPS_AIRFLOW,
        "delta_t_min": 5.0,
        "fan_on_min": 0.01,
        "confirm_min": confirm_seconds / 60.0,
        "mode_delay_min": 0.0,
        "startup_delay_min": 0.0,
    }


def rewrite_raw_fault_probe(sql: str, equipment_id: str) -> str:
    text = sql.strip().rstrip(";")
    lower = text.lower()
    final_at = lower.find("final as")
    if final_at < 0:
        raise ValueError("rendered FC6 SQL missing final aggregate")
    head = text[:final_at].rstrip().rstrip(",")
    return (
        f"{head}\nSELECT equipment_id, timestamp_utc, raw_fault\n"
        f"FROM base\nWHERE equipment_id = '{equipment_id}'\nORDER BY timestamp_utc"
    )


def case_metadata() -> dict[str, Any]:
    return {
        "design_cfm": DESIGN_CFM,
        "design_l_s": DESIGN_L_S,
        "vav_total_l_s": VAV_TOTAL_L_S,
        "perc_oa_min": PERC_OA_MIN,
        "eps_airflow": EPS_AIRFLOW,
    }
