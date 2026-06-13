"""Short fault-code descriptions for RCx Central charts."""

from __future__ import annotations

# Prefix / exact hints when Edge does not send a title.
_FAULT_HINTS: dict[str, str] = {
    "SAT": "Supply air temperature",
    "SAT-FLAT": "Supply air temp flatline",
    "OAT": "Outdoor air temperature",
    "RAT": "Return air temperature",
    "MAT": "Mixed air temperature",
    "DAT": "Discharge air temperature",
    "VAV": "VAV zone fault",
    "VAV-C": "Zone comfort / cooling",
    "VAV-03": "VAV damper extreme",
    "AHU": "Air handler fault",
    "AHU-C": "AHU comfort / control",
    "AHU-B": "AHU bounds",
    "FLAT": "Sensor flatline",
    "FLATLINE": "Sensor flatline",
    "BOUNDS": "Sensor out of bounds",
    "DSP": "Duct static pressure",
    "ZONE": "Zone temperature",
    "FAN": "Fan schedule / runtime",
    "ECON": "Economizer",
    "CHW": "Chilled water",
    "HW": "Hot water / heating",
    "BOILER": "Boiler plant",
    "PUMP": "Pump fault",
}


def fault_code_hint(code: str) -> str:
    raw = str(code or "").strip()
    if not raw:
        return "Fault"
    upper = raw.upper()
    if upper in _FAULT_HINTS:
        return _FAULT_HINTS[upper]
    for key, hint in _FAULT_HINTS.items():
        if upper.startswith(key) or key in upper:
            return hint
    return raw.replace("-", " ").replace("_", " ")[:40]


def short_fault_description(*, code: str, title: str = "", rule_name: str = "", detail: str = "") -> str:
    for raw in (title, rule_name, detail):
        text = str(raw or "").strip()
        if text and text.upper() != str(code or "").upper():
            return text[:56]
    return fault_code_hint(code)
