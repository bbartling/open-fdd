"""Optional imperial-ingest helper.

``to_imperial(ds)`` re-expresses an SI dataset in the units a US building usually stores (degF, inH2O, CFM, percent for
command/position roles). A downstream app can push that through its own ingest (which converts to SI) and expect
results identical to the SI run. ``from_imperial`` is the inverse (SI -> imperial -> SI is exact within 1e-9).

Two constant sets exist in Open-FDD: ``open_fdd.units.convert`` (248.84 Pa/inH2O, 0.471947 L/s/CFM: the thresholds were
converted with them) and the NF ingest table ``nf-app/static/units.js`` / ``open_fdd.nf.units`` (249.0889, 0.4719474),
which is what the hook applies to native values. ``to_imperial(ds, ingest="nf")`` uses the NF ingest constants, so a
store that converts with NF's table returns the SI dataset exactly; the default keeps ``open_fdd.units.convert``.

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


#: The NF ingest table (nf-app/static/units.js): inches of water and CFM differ from open_fdd.units.convert in the 4th digit.
NF_PA_PER_IN_WC = 249.0889
NF_LPS_PER_CFM = 0.4719474


def _conversions(ingest: str) -> dict:
    if ingest == "convert":
        return CONVERSIONS
    if ingest != "nf":
        raise ValueError(f"unknown ingest constants {ingest!r}; expected 'convert' or 'nf'")
    return {**CONVERSIONS,
            "si:Pa": ("inH2O", lambda p: p / NF_PA_PER_IN_WC, lambda w: w * NF_PA_PER_IN_WC),
            "si:L/s": ("CFM", lambda q: q / NF_LPS_PER_CFM, lambda c: c * NF_LPS_PER_CFM)}


def _convert(ds: Dataset, which: int, target: str, ingest: str = "convert") -> Dataset:
    out = copy.deepcopy(ds)
    CONVERSIONS = _conversions(ingest)  # noqa: N806 - shadows the module table on purpose
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


def to_imperial(ds: Dataset, ingest: str = "convert") -> Dataset:
    """A copy of ``ds`` in imperial units (``meta["unit_system"] == "imperial"``). ``ingest``: see the module docstring."""
    if ds.meta.get("unit_system") == "imperial":
        raise ValueError("dataset is already imperial")
    return _convert(ds, 1, "imperial", ingest)


def from_imperial(ds: Dataset, ingest: str = "convert") -> Dataset:
    """Inverse of ``to_imperial`` (same ``ingest``): a copy of ``ds`` back in SI."""
    if ds.meta.get("unit_system") != "imperial":
        raise ValueError("dataset is not imperial")
    out = _convert(ds, 2, "si", ingest)
    out.meta.pop("unit_system", None)
    return out
