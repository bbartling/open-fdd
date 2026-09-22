"""EQ-VOCAB: versioned engineering quantity records (ofdd_engineering_quantities_v1).

Public vocabulary lives under ``data/ofdd_engineering_quantities_v1.ttl`` (and a
Pages copy under ``docs/modeling/vocab/``). This module validates JSON quantity
records and loads the shipped schema — it does not invent capacities.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from importlib import resources
from math import isfinite
from pathlib import Path
from typing import Any

EQ_VOCAB_VERSION = "ofdd_engineering_quantities_v1"

ALLOWED_PROPERTIES = frozenset(
    {
        "ratedCoolingCapacity",
        "ratedHeatingCapacity",
        "ratedFuelInputPower",
        "ratedElectricalInputPower",
        "ratedShaftPower",
        "designSupplyAirflow",
        "designOutdoorAirflow",
        "designWaterFlow",
        "designExternalStaticPressure",
        "designPumpHead",
        "ratedCOP",
        "ratedEER",
        "ratedThermalEfficiency",
    }
)

ALLOWED_KINDS = frozenset(
    {
        "ThermalPower",
        "ElectricalPower",
        "ShaftPower",
        "VolumeFlow",
        "Pressure",
        "Efficiency",
        "Energy",
        "CoolingLoad",
    }
)

ALLOWED_BASES = frozenset({"Design", "Rated", "TAB", "Measured", "Assumed"})
ALLOWED_REVIEW = frozenset({"NeedsReview", "Reviewed", "Rejected"})

# Dimensional families for adapter checks (same physical dimension ≠ same meaning).
UNIT_FAMILIES: dict[str, str] = {
    "kW": "power",
    "W": "power",
    "hp": "shaft_power",
    "Btu/h": "thermal_power",
    "ton": "cooling_capacity",
    "tons": "cooling_capacity",
    "CFM": "airflow",
    "cfm": "airflow",
    "m3/s": "airflow_si",
    "gpm": "water_flow",
    "L/s": "water_flow_si",
    "inH2O": "pressure",
    "Pa": "pressure",
    "ft": "head",
    "kWh": "energy",
    "therms": "energy_gas",
    "MMBtu": "energy_heat",
    "-": "dimensionless",
    "fraction": "dimensionless",
    "%": "percent",
    "COP": "efficiency_cop",
    "EER": "efficiency_eer",
}

PROPERTY_KIND: dict[str, str] = {
    "ratedCoolingCapacity": "ThermalPower",
    "ratedHeatingCapacity": "ThermalPower",
    "ratedFuelInputPower": "ThermalPower",
    "ratedElectricalInputPower": "ElectricalPower",
    "ratedShaftPower": "ShaftPower",
    "designSupplyAirflow": "VolumeFlow",
    "designOutdoorAirflow": "VolumeFlow",
    "designWaterFlow": "VolumeFlow",
    "designExternalStaticPressure": "Pressure",
    "designPumpHead": "Pressure",
    "ratedCOP": "Efficiency",
    "ratedEER": "Efficiency",
    "ratedThermalEfficiency": "Efficiency",
}


@dataclass
class EngineeringQuantity:
    """One typed capacity / flow / efficiency evidence record."""

    quantity_id: str
    property: str
    numeric_value: float
    unit_code: str
    quantity_kind: str
    value_basis: str
    source_type: str
    schema_version: str = EQ_VOCAB_VERSION
    equipment_id: str = ""
    building_id: str = ""
    tenant_id: str = ""
    source_reference: str = ""
    source_locator: str = ""
    review_status: str = "NeedsReview"
    notes: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extras = d.pop("extras", {}) or {}
        d.update(extras)
        return {k: v for k, v in d.items() if v != "" and v != {}}


def load_vocab_ttl() -> str:
    """Return the shipped vocabulary Turtle text."""
    return (
        resources.files("open_fdd.ecm_engineering")
        .joinpath("data/ofdd_engineering_quantities_v1.ttl")
        .read_text(encoding="utf-8")
    )


def load_quantity_schema() -> dict[str, Any]:
    raw = (
        resources.files("open_fdd.ecm_engineering")
        .joinpath("data/ofdd_engineering_quantities_v1.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)


def engineering_quantity_from_dict(doc: dict[str, Any]) -> EngineeringQuantity:
    known = {
        "schema_version",
        "quantity_id",
        "property",
        "numeric_value",
        "unit_code",
        "quantity_kind",
        "value_basis",
        "source_type",
        "equipment_id",
        "building_id",
        "tenant_id",
        "source_reference",
        "source_locator",
        "review_status",
        "notes",
    }
    extras = {k: v for k, v in doc.items() if k not in known}
    return EngineeringQuantity(
        schema_version=str(doc.get("schema_version") or EQ_VOCAB_VERSION),
        quantity_id=str(doc["quantity_id"]),
        property=str(doc["property"]),
        numeric_value=float(doc["numeric_value"]),
        unit_code=str(doc["unit_code"]),
        quantity_kind=str(doc["quantity_kind"]),
        value_basis=str(doc["value_basis"]),
        source_type=str(doc["source_type"]),
        equipment_id=str(doc.get("equipment_id") or ""),
        building_id=str(doc.get("building_id") or ""),
        tenant_id=str(doc.get("tenant_id") or ""),
        source_reference=str(doc.get("source_reference") or ""),
        source_locator=str(doc.get("source_locator") or ""),
        review_status=str(doc.get("review_status") or "NeedsReview"),
        notes=str(doc.get("notes") or ""),
        extras=extras,
    )


def validate_engineering_quantity(doc: dict[str, Any]) -> list[str]:
    """Return a list of validation issues (empty = ok). No silent coercion."""
    issues: list[str] = []
    if not isinstance(doc, dict):
        return ["quantity must be an object"]
    ver = doc.get("schema_version", EQ_VOCAB_VERSION)
    if ver != EQ_VOCAB_VERSION:
        issues.append(f"unsupported schema_version {ver!r}; expected {EQ_VOCAB_VERSION}")
    for key in (
        "quantity_id",
        "property",
        "numeric_value",
        "unit_code",
        "quantity_kind",
        "value_basis",
        "source_type",
    ):
        if key not in doc or doc[key] in (None, ""):
            issues.append(f"missing required field: {key}")
    prop = doc.get("property")
    if prop is not None and prop not in ALLOWED_PROPERTIES:
        issues.append(f"unknown property: {prop}")
    kind = doc.get("quantity_kind")
    if kind is not None and kind not in ALLOWED_KINDS:
        issues.append(f"unknown quantity_kind: {kind}")
    if prop in PROPERTY_KIND and kind is not None and kind != PROPERTY_KIND[prop]:
        issues.append(
            f"quantity_kind {kind!r} incompatible with property {prop!r} "
            f"(expected {PROPERTY_KIND[prop]})"
        )
    basis = doc.get("value_basis")
    if basis is not None and basis not in ALLOWED_BASES:
        issues.append(f"unknown value_basis: {basis}")
    review = doc.get("review_status")
    if review is not None and review not in ALLOWED_REVIEW:
        issues.append(f"unknown review_status: {review}")
    try:
        val = float(doc["numeric_value"]) if "numeric_value" in doc else float("nan")
        if not isfinite(val):
            issues.append("numeric_value must be finite")
    except (TypeError, ValueError, KeyError):
        issues.append("numeric_value must be a finite number")
    unit = doc.get("unit_code")
    if isinstance(unit, str) and unit and unit not in UNIT_FAMILIES:
        # Unknown units are allowed with a warning-style issue (not hard reject)
        # so sites can introduce local codes with human review.
        issues.append(f"unregistered unit_code: {unit} (review required)")
    return issues


def unit_family(unit_code: str) -> str | None:
    return UNIT_FAMILIES.get(unit_code)


def docs_vocab_paths() -> tuple[Path, Path]:
    """Repo-relative Pages copies used by the parity test."""
    root = Path(__file__).resolve().parents[2]
    base = root / "docs" / "modeling" / "vocab"
    return (
        base / "ofdd_engineering_quantities_v1.ttl",
        base / "ofdd_engineering_quantities_v1.schema.json",
    )


__all__ = [
    "ALLOWED_PROPERTIES",
    "EQ_VOCAB_VERSION",
    "EngineeringQuantity",
    "docs_vocab_paths",
    "engineering_quantity_from_dict",
    "load_quantity_schema",
    "load_vocab_ttl",
    "unit_family",
    "validate_engineering_quantity",
]
