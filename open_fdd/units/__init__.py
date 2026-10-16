"""Shared unit conversion helpers for Open-FDD (oracle / tests / reports).

Processing ABI target is metric. Current SQL pack remains imperial-f-v1 until
metric-v2 equations ship; admit helpers convert known source units into the
active pack ABI.
"""

from __future__ import annotations

from open_fdd.units.convert import (
    PA_PER_IN_WC,
    admit_temperature_to_pack_f,
    celsius_to_fahrenheit,
    delta_c_to_delta_f,
    delta_f_to_delta_c,
    fahrenheit_to_celsius,
    norm_command,
    normalize_unit_token,
)

__all__ = [
    "PA_PER_IN_WC",
    "admit_temperature_to_pack_f",
    "celsius_to_fahrenheit",
    "delta_c_to_delta_f",
    "delta_f_to_delta_c",
    "fahrenheit_to_celsius",
    "norm_command",
    "normalize_unit_token",
]
