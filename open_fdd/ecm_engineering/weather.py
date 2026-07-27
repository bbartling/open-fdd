"""Weather-bin and psychrometric helpers for Open-FDD ECM screening."""
from __future__ import annotations
from dataclasses import dataclass
from math import exp, log
from typing import Any, Iterable, Sequence

P_ATM_PSIA = 14.696


def saturation_pressure_psia(t_f: float) -> float:
    """Saturation pressure over liquid water using a Hyland-Wexler form."""
    tr = float(t_f) + 459.67
    ln_p = (
        -1.0440397e4 / tr
        - 1.129465e1
        - 2.7022355e-2 * tr
        + 1.289036e-5 * tr**2
        - 2.4780681e-9 * tr**3
        + 6.5459673 * log(tr)
    )
    return exp(ln_p)


def humidity_ratio_from_rh(t_f: float, rh_fraction: float, pressure_psia: float = P_ATM_PSIA) -> float:
    rh = float(rh_fraction)
    if not 0 <= rh <= 1:
        raise ValueError("rh_fraction must be 0..1")
    pv = rh * saturation_pressure_psia(t_f)
    if pv >= pressure_psia:
        raise ValueError("vapor pressure must be below barometric pressure")
    return 0.621945 * pv / (pressure_psia - pv)


def moist_air_enthalpy_btu_lb(t_f: float, w: float) -> float:
    return 0.240 * float(t_f) + float(w) * (1061.0 + 0.444 * float(t_f))


def saturated_enthalpy_btu_lb(t_f: float) -> float:
    pws = saturation_pressure_psia(t_f)
    w = 0.621945 * pws / (P_ATM_PSIA - pws)
    return moist_air_enthalpy_btu_lb(t_f, w)


@dataclass(frozen=True)
class OperatingSchedule:
    shifts: tuple[float, float, float]
    days_per_week: float
    override_allowance: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperatingSchedule":
        shifts = tuple(float(x) for x in data["shifts"])
        if len(shifts) != 3:
            raise ValueError("shifts must have three 8-hour values")
        return cls(shifts=shifts, days_per_week=float(data["days_per_week"]), override_allowance=float(data.get("override_allowance", 0.0)))  # type: ignore[arg-type]

    @property
    def weekly_hours(self) -> float:
        return sum(self.shifts) * self.days_per_week * (1.0 + self.override_allowance)

    def total_operating_hours(self, shift_bin_hours: Sequence[float]) -> float:
        if len(shift_bin_hours) != 3:
            raise ValueError("shift_bin_hours must have three values")
        return sum(float(shift_bin_hours[i]) * self.shifts[i] / 8.0 * self.days_per_week / 7.0 for i in range(3))


def hours_reduction_fraction(existing: OperatingSchedule, proposed: OperatingSchedule) -> float:
    if existing.weekly_hours <= 0:
        return 0.0
    return (existing.weekly_hours - proposed.weekly_hours) / existing.weekly_hours


@dataclass(frozen=True)
class BinRow:
    temp_f: float
    shift_hours: tuple[float, float, float]
    wetbulb_f: float | None = None
    enthalpy_btu_lb: float | None = None

    @property
    def annual_hours(self) -> float:
        return sum(self.shift_hours)

    @property
    def oa_enthalpy(self) -> float | None:
        if self.enthalpy_btu_lb is not None:
            return self.enthalpy_btu_lb
        if self.wetbulb_f is not None:
            return saturated_enthalpy_btu_lb(self.wetbulb_f)
        return None


@dataclass(frozen=True)
class WeatherBins:
    rows: tuple[BinRow, ...]
    source: str = ""

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]], source: str = "") -> "WeatherBins":
        parsed: list[BinRow] = []
        for row in rows:
            if "shift_hours" in row:
                shifts = tuple(float(v) for v in row["shift_hours"])
            else:
                h = float(row["hours"]) / 3.0
                shifts = (h, h, h)
            if len(shifts) != 3:
                raise ValueError("shift_hours must have 3 values")
            parsed.append(BinRow(temp_f=float(row["temp_f"]), shift_hours=shifts, wetbulb_f=None if row.get("wetbulb_f") is None else float(row["wetbulb_f"]), enthalpy_btu_lb=None if row.get("enthalpy_btu_lb") is None else float(row["enthalpy_btu_lb"])))  # type: ignore[arg-type]
        parsed.sort(key=lambda row: row.temp_f, reverse=True)
        return cls(tuple(parsed), source=source)

    @property
    def total_hours(self) -> float:
        return sum(row.annual_hours for row in self.rows)
