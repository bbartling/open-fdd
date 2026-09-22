"""ECM-ADAPT: map EQ-VOCAB quantity records → ``open_fdd.ecm_engineering.calculate``.

Python stays on PyPI. This adapter never invents tariffs, hours, or capacities —
missing evidence is returned as structured gaps instead of a savings result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .algorithms import calculate
from .eq_vocab import (
    EngineeringQuantity,
    engineering_quantity_from_dict,
    unit_family,
    validate_engineering_quantity,
)

# Calculator input key → (property name, accepted unit families)
METHOD_REQUIREMENTS: dict[str, dict[str, tuple[str, frozenset[str]]]] = {
    "fan_affinity": {
        "design_kw": ("ratedElectricalInputPower", frozenset({"power"})),
    },
    "schedule_reduction": {
        "equipment_kw": ("ratedElectricalInputPower", frozenset({"power"})),
    },
    "kw_per_ton_improvement": {
        # Nameplate cooling alone cannot establish annual load — ton-hours stay
        # scenario-supplied. Capacity is optional context only.
    },
}

# Scenario keys always required (not model quantities).
METHOD_SCENARIO_REQUIRED: dict[str, frozenset[str]] = {
    "fan_affinity": frozenset(
        {"hours", "baseline_speed_fraction", "proposed_speed_fraction"}
    ),
    "schedule_reduction": frozenset({"baseline_annual_hours", "proposed_annual_hours"}),
    "kw_per_ton_improvement": frozenset(
        {"annual_ton_hours", "baseline_kw_per_ton", "proposed_kw_per_ton"}
    ),
}


@dataclass
class AdaptIssue:
    code: str
    message: str
    field: str = ""


@dataclass
class AdaptResult:
    ok: bool
    method: str
    inputs: dict[str, Any] = field(default_factory=dict)
    selected_quantity_ids: list[str] = field(default_factory=list)
    missing_evidence: list[AdaptIssue] = field(default_factory=list)
    blocking_issues: list[AdaptIssue] = field(default_factory=list)
    result: dict[str, Any] | None = None
    adapter_version: str = "ecm_adapt_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "method": self.method,
            "adapter_version": self.adapter_version,
            "inputs": self.inputs,
            "selected_quantity_ids": self.selected_quantity_ids,
            "missing_evidence": [i.__dict__ for i in self.missing_evidence],
            "blocking_issues": [i.__dict__ for i in self.blocking_issues],
            "result": self.result,
        }


def _as_quantities(
    quantities: list[EngineeringQuantity | dict[str, Any]],
) -> tuple[list[EngineeringQuantity], list[AdaptIssue]]:
    out: list[EngineeringQuantity] = []
    issues: list[AdaptIssue] = []
    for raw in quantities:
        if isinstance(raw, EngineeringQuantity):
            doc = raw.to_dict()
            q = raw
        else:
            doc = raw
            try:
                q = engineering_quantity_from_dict(doc)
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(
                    AdaptIssue("invalid_quantity", f"cannot parse quantity: {exc}")
                )
                continue
        for msg in validate_engineering_quantity(doc):
            # Unregistered unit is soft; others block.
            if msg.startswith("unregistered unit_code"):
                continue
            issues.append(AdaptIssue("invalid_quantity", msg, q.quantity_id))
        out.append(q)
    return out, issues


def _select_property(
    quantities: list[EngineeringQuantity],
    property_name: str,
    families: frozenset[str],
) -> tuple[EngineeringQuantity | None, list[AdaptIssue]]:
    matches = [q for q in quantities if q.property == property_name]
    if not matches:
        return None, [
            AdaptIssue(
                "missing_quantity",
                f"no quantity with property {property_name}",
                property_name,
            )
        ]
    # Prefer Reviewed, then Measured/TAB/Rated over Assumed.
    basis_rank = {"Measured": 0, "TAB": 1, "Rated": 2, "Design": 3, "Assumed": 4}
    review_rank = {"Reviewed": 0, "NeedsReview": 1, "Rejected": 9}
    matches.sort(
        key=lambda q: (
            review_rank.get(q.review_status, 5),
            basis_rank.get(q.value_basis, 5),
            q.quantity_id,
        )
    )
    chosen = matches[0]
    if chosen.review_status == "Rejected":
        return None, [
            AdaptIssue(
                "rejected_quantity",
                f"only Rejected records for {property_name}",
                chosen.quantity_id,
            )
        ]
    fam = unit_family(chosen.unit_code)
    if fam is None or fam not in families:
        return None, [
            AdaptIssue(
                "unit_mismatch",
                f"{property_name} unit {chosen.unit_code!r} not in {sorted(families)}",
                chosen.quantity_id,
            )
        ]
    # Thermal kW must not silently feed electrical design_kw.
    if property_name == "ratedElectricalInputPower" and chosen.quantity_kind != "ElectricalPower":
        return None, [
            AdaptIssue(
                "kind_mismatch",
                "ratedElectricalInputPower requires quantity_kind ElectricalPower "
                "(thermal kW is not electrical demand)",
                chosen.quantity_id,
            )
        ]
    return chosen, []


def adapt_model_to_calculator(
    method: str,
    quantities: list[EngineeringQuantity | dict[str, Any]],
    scenario: dict[str, Any] | None = None,
    *,
    run: bool = True,
) -> AdaptResult:
    """Map model quantities + scenario → calculator inputs (and optionally run)."""
    scenario = dict(scenario or {})
    if method not in METHOD_SCENARIO_REQUIRED:
        return AdaptResult(
            ok=False,
            method=method,
            blocking_issues=[
                AdaptIssue(
                    "unsupported_method",
                    f"adapter supports {sorted(METHOD_SCENARIO_REQUIRED)}; got {method!r}",
                )
            ],
        )

    qs, parse_issues = _as_quantities(quantities)
    blocking = list(parse_issues)
    missing: list[AdaptIssue] = []
    inputs: dict[str, Any] = {}
    selected: list[str] = []

    for key, (prop, families) in METHOD_REQUIREMENTS.get(method, {}).items():
        chosen, issues = _select_property(qs, prop, families)
        if chosen is None:
            missing.extend(issues)
            continue
        inputs[key] = float(chosen.numeric_value)
        selected.append(chosen.quantity_id)

    for key in METHOD_SCENARIO_REQUIRED[method]:
        if key not in scenario or scenario[key] in (None, ""):
            missing.append(
                AdaptIssue(
                    "missing_scenario",
                    f"scenario missing required field: {key}",
                    key,
                )
            )
        else:
            try:
                inputs[key] = float(scenario[key])
            except (TypeError, ValueError):
                blocking.append(
                    AdaptIssue("invalid_scenario", f"{key} must be numeric", key)
                )

    # Optional passthroughs (e.g. power_exponent, average_load_fraction).
    for opt in ("power_exponent", "average_load_fraction"):
        if opt in scenario:
            try:
                inputs[opt] = float(scenario[opt])
            except (TypeError, ValueError):
                blocking.append(
                    AdaptIssue("invalid_scenario", f"{opt} must be numeric", opt)
                )

    if method == "kw_per_ton_improvement":
        # Explicit honesty: capacity-only models cannot invent annual_ton_hours.
        cool = [q for q in qs if q.property == "ratedCoolingCapacity"]
        if cool and "annual_ton_hours" not in scenario:
            missing.append(
                AdaptIssue(
                    "capacity_only",
                    "ratedCoolingCapacity present but annual_ton_hours missing — "
                    "nameplate capacity alone cannot establish annual load",
                    cool[0].quantity_id,
                )
            )

    if missing or blocking:
        return AdaptResult(
            ok=False,
            method=method,
            inputs=inputs,
            selected_quantity_ids=selected,
            missing_evidence=missing,
            blocking_issues=blocking,
        )

    if not run:
        return AdaptResult(
            ok=True,
            method=method,
            inputs=inputs,
            selected_quantity_ids=selected,
        )

    try:
        result = calculate(method, inputs)
    except Exception as exc:  # noqa: BLE001 — surface calculator contract errors
        return AdaptResult(
            ok=False,
            method=method,
            inputs=inputs,
            selected_quantity_ids=selected,
            blocking_issues=[AdaptIssue("calculator_error", str(exc))],
        )

    return AdaptResult(
        ok=True,
        method=method,
        inputs=inputs,
        selected_quantity_ids=selected,
        result=result,
    )


__all__ = [
    "AdaptIssue",
    "AdaptResult",
    "METHOD_REQUIREMENTS",
    "METHOD_SCENARIO_REQUIRED",
    "adapt_model_to_calculator",
]
