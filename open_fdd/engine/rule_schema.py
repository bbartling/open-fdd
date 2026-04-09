"""
Optional Pydantic validation/coercion for rule ``params`` (schedule, weather_band, scalars).

Keeps arbitrary extra keys (rolling_window, thresholds, etc.) while tightening nested
structures used by :mod:`open_fdd.engine.schedule_masks`.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleSpec(BaseModel):
    """``params.schedule`` for schedule_occupied injection."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    weekdays: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4],
        description="Mon=0 … Sun=6",
    )
    start_hour: int = Field(8, ge=0, le=23)
    end_hour: int = Field(17, ge=0, le=24)

    @field_validator("weekdays", mode="before")
    @classmethod
    def _coerce_weekdays(cls, v: Any) -> list[int]:
        if v is None:
            return [0, 1, 2, 3, 4]
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        raise TypeError("weekdays must be a list of integers")


class WeatherBandSpec(BaseModel):
    """``params.weather_band`` for weather_allows_fdd injection."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    oat_input: str = "Outside_Air_Temperature_Sensor"
    low: float = Field(32.0, description="Band low (°F or °C per units)")
    high: float = Field(85.0, description="Band high")
    units: Literal["imperial", "metric"] = "imperial"


def coerce_rule_params(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Return a copy of ``params`` with validated ``schedule`` / ``weather_band`` and
    best-effort coercion of string numerics for scalar values.

    Unknown keys are preserved. Invalid nested ``schedule`` / ``weather_band`` raises
    ``ValueError`` with a clear message (fail fast on misconfigured YAML).
    """
    if not raw:
        return {}
    out: Dict[str, Any] = dict(raw)

    sched = out.get("schedule")
    if isinstance(sched, dict):
        out["schedule"] = ScheduleSpec.model_validate(sched).model_dump()

    wb = out.get("weather_band")
    if isinstance(wb, dict):
        out["weather_band"] = WeatherBandSpec.model_validate(wb).model_dump()

    for k, v in list(out.items()):
        if k in ("schedule", "weather_band") or isinstance(v, (dict, list, tuple, bool)):
            continue
        if isinstance(v, str) and v.strip() != "":
            try:
                out[k] = float(v) if any(c in v for c in ".eE") else int(v)
            except ValueError:
                pass

    return out
