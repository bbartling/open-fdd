"""Optional imperial-ingest helper.

``to_imperial(ds)`` re-expresses an SI dataset in the units a US building usually stores (degF, inH2O, CFM, percent for
command/position roles). A downstream app can push that through its own ingest (which converts to SI) and expect
results identical to the SI run. ``from_imperial`` is the inverse (SI -> imperial -> SI is exact within 1e-9).

Only roles with a known conversion change: ``si:degC``, ``si:Pa``, ``si:L/s`` and ``fraction`` (0-1 -> 0-100 percent).
Statuses (0/1), relative humidity, kW, kWh, A, ppm and counts are the same in both systems.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from open_fdd.parity.dataset import Dataset
from open_fdd.units.convert import LPS_PER_CFM, PA_PER_IN_WC

_SCALES = json.loads((Path(__file__).resolve().parent.parent / "data" / "role_scales.json").read_text(encoding="utf-8"))["roles"]

#: scale -> (imperial unit, SI -> imperial, imperial -> SI)
CONVERSIONS = {
    "si:degC": ("°F", lambda c: c * 9.0 / 5.0 + 32.0, lambda f: (f - 32.0) * 5.0 / 9.0),
    "si:Pa": ("inH2O", lambda p: p / PA_PER_IN_WC, lambda w: w * PA_PER_IN_WC),
    "si:L/s": ("CFM", lambda q: q / LPS_PER_CFM, lambda c: c * LPS_PER_CFM),
    "fraction": ("%", lambda x: x * 100.0, lambda x: x / 100.0),
}
_SI_UNIT = {"si:degC": "°C", "si:Pa": "Pa", "si:L/s": "L/s", "fraction": "fraction"}
_UNIT_BY_SYSTEM = {  # series/authorization unit tokens
    "imperial": {"°C": "°F", "Pa": "inH2O", "L/s": "CFM"},
    "si": {"°F": "°C", "inH2O": "Pa", "CFM": "L/s"},
}


def _convert(ds: Dataset, which: int, target: str) -> Dataset:
    out = copy.deepcopy(ds)
    plan = {col: CONVERSIONS[scale] for col, scale in _SCALES.items() if scale in CONVERSIONS}
    for row in out.history:
        for col, conv in plan.items():
            v = row.get(col)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                row[col] = conv[which](v)
    for f in out.faults:  # planted-fault values are in the dataset's units too
        if f.get("column") in plan and f.get("value") is not None:
            f["value"] = plan[f["column"]][which](f["value"])
    for w in out.weather:  # weather roles are outdoor temperatures
        for k in ("oa_t", "web_oa_t", "web_oa_dp"):
            if w.get(k) is not None:
                w[k] = CONVERSIONS["si:degC"][which](w[k])
    tokens = _UNIT_BY_SYSTEM[target]
    for table in (out.authorized_series, out.series):
        for r in table:
            r["unit"] = tokens.get(r["unit"], r["unit"])
    out.units = {role: tokens.get(u, u) for role, u in out.units.items()}
    for p in out.model["points"]:
        scale = p.get("scale")
        if scale in CONVERSIONS:
            p["unit"] = CONVERSIONS[scale][0] if target == "imperial" else _SI_UNIT[scale]
    out.meta = {**out.meta, "unit_system": target}
    return out


def to_imperial(ds: Dataset) -> Dataset:
    """A copy of ``ds`` in imperial units (``meta["unit_system"] == "imperial"``)."""
    if ds.meta.get("unit_system") == "imperial":
        raise ValueError("dataset is already imperial")
    return _convert(ds, 1, "imperial")


def from_imperial(ds: Dataset) -> Dataset:
    """Inverse of ``to_imperial``: a copy of ``ds`` back in SI."""
    if ds.meta.get("unit_system") != "imperial":
        raise ValueError("dataset is not imperial")
    out = _convert(ds, 2, "si")
    out.meta.pop("unit_system", None)
    return out
