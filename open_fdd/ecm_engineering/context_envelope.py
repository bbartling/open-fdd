"""Versioned ECM context envelope (ecm_context_v1).

Extends Stage-1 contracts / provenance — does not fork calculators.
Python stays on PyPI; never wire this into central/web request paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .contracts import InteractionStatus, SourceType
from .provenance import EvidenceValue, ProvenanceClass

ECM_CONTEXT_SCHEMA_VERSION = "ecm_context_v1"

# Units that must not be silently mixed for the same quantity family.
_INCOMPATIBLE_UNIT_PAIRS = frozenset(
    {
        frozenset({"hp", "kW"}),
        frozenset({"hp", "kw"}),
        frozenset({"°F", "°C"}),
        frozenset({"F", "C"}),
        frozenset({"cfm", "m3/s"}),
        frozenset({"therms", "kWh"}),
        frozenset({"therms", "kwh"}),
    }
)


class ReadinessStatus(StrEnum):
    SCREENING = "screening"
    VALIDATED = "validated"
    SUBMISSION_READY = "submission_ready"


class AssetKind(StrEnum):
    SUPPLY_FAN = "supply_fan"
    RETURN_FAN = "return_fan"
    PUMP = "pump"
    MOTOR = "motor"
    VFD = "vfd"
    CHILLER = "chiller"
    BOILER = "boiler"
    COIL = "coil"
    METER = "meter"
    OTHER = "other"


@dataclass
class PointProvenance:
    """Command or power point binding for a physical asset."""

    role: str
    point_id: str
    source_type: SourceType
    units: str = ""
    transform: str = ""
    proxy_of: str = ""
    proxy_warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        return d


@dataclass
class EquipmentAsset:
    asset_id: str
    kind: AssetKind
    equipment_id: str
    nameplate: dict[str, EvidenceValue] = field(default_factory=dict)
    measured: dict[str, EvidenceValue] = field(default_factory=dict)
    command_point: PointProvenance | None = None
    power_point: PointProvenance | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "kind": self.kind.value,
            "equipment_id": self.equipment_id,
            "nameplate": {k: v.as_dict() for k, v in self.nameplate.items()},
            "measured": {k: v.as_dict() for k, v in self.measured.items()},
            "command_point": self.command_point.as_dict() if self.command_point else None,
            "power_point": self.power_point.as_dict() if self.power_point else None,
        }


@dataclass
class RoleQuality:
    role: str
    source_point: str
    units: str
    transform: str = ""
    sample_window: str = ""
    sample_count: int = 0
    valid_pct: float | None = None
    gap_policy: str = ""
    outlier_pct: float | None = None
    min: float | None = None
    median: float | None = None
    mean: float | None = None
    p95: float | None = None
    max: float | None = None
    quality_warnings: list[str] = field(default_factory=list)
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BaselineMetric:
    name: str
    value: float | None
    unit: str
    method: str
    observed_window: str = ""
    annualized: bool = False
    annualization_method_version: str = ""
    denominator: str = ""
    extrapolation_period: str = ""
    calendar_source: str = ""
    weather_source: str = ""
    uncertainty_note: str = ""
    provenance: ProvenanceClass = ProvenanceClass.UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.value
        return d


@dataclass
class TariffContext:
    energy_rate: float | None = None
    demand_rate: float | None = None
    currency: str = "USD"
    ratchet: str = ""
    on_peak_periods: list[str] = field(default_factory=list)
    fuel_rates: dict[str, float] = field(default_factory=dict)
    escalation: float | None = None
    effective_dates: str = ""
    source: str = ""
    avoided_cost_method: str = ""
    monetary_available: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EcmScenario:
    scenario_id: str
    calculator: str
    baseline: dict[str, Any] = field(default_factory=dict)
    proposed: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    constraints: list[str] = field(default_factory=list)
    realization_factor: float = 1.0
    effective_dates: str = ""
    author: str = ""
    review_status: str = "draft"
    parameters: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalcResult:
    calculator: str
    package_version: str
    calculator_version: str = ""
    formula_hash: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)
    realization_adjusted: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    test_vector_id: str = ""
    readiness: ReadinessStatus = ReadinessStatus.SCREENING
    human_review: bool = False

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["readiness"] = self.readiness.value
        return d


@dataclass
class MeasureInteraction:
    measure_id: str
    interaction_group: str
    calculation_order: int
    affected_end_uses: list[str] = field(default_factory=list)
    affected_hours: str = ""
    depends_on: list[str] = field(default_factory=list)
    interaction_status: InteractionStatus = InteractionStatus.NOT_EVALUATED
    method: str = "remaining_runtime"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["interaction_status"] = self.interaction_status.value
        return d


@dataclass
class GapItem:
    code: str
    message: str
    severity: str = "warning"
    asset_id: str = ""
    recommended_action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EcmContext:
    """Machine-readable ECM screening context (schema ecm_context_v1)."""

    schema_version: str = ECM_CONTEXT_SCHEMA_VERSION
    building_id: str = ""
    tenant_id: str = ""
    equipment_ids: list[str] = field(default_factory=list)
    equipment_types: dict[str, str] = field(default_factory=dict)
    timezone: str = "UTC"
    unit_system: str = "imperial"
    retrieved_at: str = ""
    api_or_package_version: str = ""
    source_revision: str = ""
    assets: list[EquipmentAsset] = field(default_factory=list)
    roles: list[RoleQuality] = field(default_factory=list)
    baselines: list[BaselineMetric] = field(default_factory=list)
    scenario: EcmScenario | None = None
    tariff: TariffContext = field(default_factory=TariffContext)
    calc_result: CalcResult | None = None
    interactions: list[MeasureInteraction] = field(default_factory=list)
    missing_evidence: list[GapItem] = field(default_factory=list)
    assumptions_required: list[GapItem] = field(default_factory=list)
    blocking_issues: list[GapItem] = field(default_factory=list)
    recommended_measurements: list[GapItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "building_id": self.building_id,
            "tenant_id": self.tenant_id,
            "equipment_ids": list(self.equipment_ids),
            "equipment_types": dict(self.equipment_types),
            "timezone": self.timezone,
            "unit_system": self.unit_system,
            "retrieved_at": self.retrieved_at,
            "api_or_package_version": self.api_or_package_version,
            "source_revision": self.source_revision,
            "assets": [a.as_dict() for a in self.assets],
            "roles": [r.as_dict() for r in self.roles],
            "baselines": [b.as_dict() for b in self.baselines],
            "scenario": self.scenario.as_dict() if self.scenario else None,
            "tariff": self.tariff.as_dict(),
            "calc_result": self.calc_result.as_dict() if self.calc_result else None,
            "interactions": [i.as_dict() for i in self.interactions],
            "missing_evidence": [g.as_dict() for g in self.missing_evidence],
            "assumptions_required": [g.as_dict() for g in self.assumptions_required],
            "blocking_issues": [g.as_dict() for g in self.blocking_issues],
            "recommended_measurements": [g.as_dict() for g in self.recommended_measurements],
        }


def ecm_context_from_dict(doc: dict[str, Any]) -> EcmContext:
    """Best-effort round-trip loader (schema validation is separate)."""
    if not isinstance(doc, dict):
        raise TypeError("ecm context root must be an object")
    ctx = EcmContext(
        schema_version=str(doc.get("schema_version") or ""),
        building_id=str(doc.get("building_id") or ""),
        tenant_id=str(doc.get("tenant_id") or ""),
        equipment_ids=list(doc.get("equipment_ids") or []),
        equipment_types=dict(doc.get("equipment_types") or {}),
        timezone=str(doc.get("timezone") or "UTC"),
        unit_system=str(doc.get("unit_system") or "imperial"),
        retrieved_at=str(doc.get("retrieved_at") or ""),
        api_or_package_version=str(doc.get("api_or_package_version") or ""),
        source_revision=str(doc.get("source_revision") or ""),
    )
    for a in doc.get("assets") or []:
        if not isinstance(a, dict):
            continue
        kind = AssetKind(a.get("kind") or AssetKind.OTHER.value)
        asset = EquipmentAsset(
            asset_id=str(a.get("asset_id") or ""),
            kind=kind,
            equipment_id=str(a.get("equipment_id") or ""),
        )
        for bag_name in ("nameplate", "measured"):
            bag = a.get(bag_name) or {}
            if not isinstance(bag, dict):
                continue
            target = asset.nameplate if bag_name == "nameplate" else asset.measured
            for k, v in bag.items():
                if isinstance(v, dict):
                    target[k] = EvidenceValue(
                        value=v.get("value"),
                        provenance=ProvenanceClass(v.get("provenance") or "UNKNOWN"),
                        source=str(v.get("source") or ""),
                        method=str(v.get("method") or ""),
                        confidence=str(v.get("confidence") or "unknown"),
                        timestamp=v.get("timestamp"),
                    )
        for pt_name in ("command_point", "power_point"):
            pt = a.get(pt_name)
            if isinstance(pt, dict) and pt.get("point_id"):
                bound = PointProvenance(
                    role=str(pt.get("role") or ""),
                    point_id=str(pt.get("point_id") or ""),
                    source_type=SourceType(pt.get("source_type") or SourceType.HUMAN_ENTERED.value),
                    units=str(pt.get("units") or ""),
                    transform=str(pt.get("transform") or ""),
                    proxy_of=str(pt.get("proxy_of") or ""),
                    proxy_warning=str(pt.get("proxy_warning") or ""),
                )
                if pt_name == "command_point":
                    asset.command_point = bound
                else:
                    asset.power_point = bound
        ctx.assets.append(asset)
    tariff = doc.get("tariff") or {}
    if isinstance(tariff, dict):
        ctx.tariff = TariffContext(
            energy_rate=tariff.get("energy_rate"),
            demand_rate=tariff.get("demand_rate"),
            currency=str(tariff.get("currency") or "USD"),
            ratchet=str(tariff.get("ratchet") or ""),
            on_peak_periods=list(tariff.get("on_peak_periods") or []),
            fuel_rates=dict(tariff.get("fuel_rates") or {}),
            escalation=tariff.get("escalation"),
            effective_dates=str(tariff.get("effective_dates") or ""),
            source=str(tariff.get("source") or ""),
            avoided_cost_method=str(tariff.get("avoided_cost_method") or ""),
            monetary_available=bool(tariff.get("monetary_available")),
        )
    for key in (
        "missing_evidence",
        "assumptions_required",
        "blocking_issues",
        "recommended_measurements",
    ):
        items = doc.get(key) or []
        if not isinstance(items, list):
            continue
        gaps = [
            GapItem(
                code=str(g.get("code") or ""),
                message=str(g.get("message") or ""),
                severity=str(g.get("severity") or "warning"),
                asset_id=str(g.get("asset_id") or ""),
                recommended_action=str(g.get("recommended_action") or ""),
            )
            for g in items
            if isinstance(g, dict)
        ]
        setattr(ctx, key, gaps)
    return ctx


def validate_ecm_context(doc: dict[str, Any], *, strict: bool = True) -> list[str]:
    """Validate ecm_context_v1 shape. Empty list = ok."""
    issues: list[str] = []
    if not isinstance(doc, dict):
        return ["ecm context root must be an object"]
    ver = doc.get("schema_version")
    if ver != ECM_CONTEXT_SCHEMA_VERSION:
        issues.append(
            f"schema_version must be {ECM_CONTEXT_SCHEMA_VERSION!r}, got {ver!r}"
        )
    for key in ("building_id", "tenant_id", "retrieved_at"):
        if not str(doc.get(key) or "").strip():
            issues.append(f"missing required field: {key}")
    if not isinstance(doc.get("equipment_ids"), list):
        issues.append("equipment_ids must be a list")
    if not isinstance(doc.get("assets"), list):
        issues.append("assets must be a list")
    else:
        cmd_points: dict[str, str] = {}
        for i, a in enumerate(doc["assets"]):
            if not isinstance(a, dict):
                issues.append(f"assets[{i}] must be an object")
                continue
            for req in ("asset_id", "kind", "equipment_id"):
                if not a.get(req):
                    issues.append(f"assets[{i}] missing {req}")
            cmd = a.get("command_point") or {}
            if isinstance(cmd, dict) and cmd.get("point_id"):
                pid = str(cmd["point_id"])
                aid = str(a.get("asset_id") or f"idx{i}")
                if pid in cmd_points and cmd_points[pid] != aid:
                    if not (cmd.get("proxy_of") or cmd.get("proxy_warning")):
                        issues.append(
                            f"assets[{i}]: command point {pid!r} shared with "
                            f"{cmd_points[pid]!r} without proxy_of/proxy_warning"
                        )
                else:
                    cmd_points[pid] = aid
    if strict:
        known = {
            "schema_version",
            "building_id",
            "tenant_id",
            "equipment_ids",
            "equipment_types",
            "timezone",
            "unit_system",
            "retrieved_at",
            "api_or_package_version",
            "source_revision",
            "assets",
            "roles",
            "baselines",
            "scenario",
            "tariff",
            "calc_result",
            "interactions",
            "missing_evidence",
            "assumptions_required",
            "blocking_issues",
            "recommended_measurements",
        }
        for k in doc:
            if k not in known:
                issues.append(f"unknown field (strict): {k}")
    tariff = doc.get("tariff")
    if isinstance(tariff, dict) and tariff.get("monetary_available"):
        if tariff.get("energy_rate") is None and tariff.get("demand_rate") is None:
            issues.append("tariff.monetary_available true but no energy_rate/demand_rate")
    calc = doc.get("calc_result")
    if isinstance(calc, dict):
        readiness = calc.get("readiness")
        if readiness == ReadinessStatus.SUBMISSION_READY.value and not calc.get(
            "human_review"
        ):
            issues.append("submission_ready requires human_review=true")
    return issues


def reject_incompatible_units(unit_a: str, unit_b: str) -> str | None:
    """Return an error string when two units are in an incompatible pair."""
    a = (unit_a or "").strip()
    b = (unit_b or "").strip()
    if not a or not b or a == b:
        return None
    pair = frozenset({a, b})
    # normalize kw case
    norm = frozenset({x.lower() if x.lower() == "kw" else x for x in pair})
    if pair in _INCOMPATIBLE_UNIT_PAIRS or norm in _INCOMPATIBLE_UNIT_PAIRS:
        return f"incompatible units: {a!r} vs {b!r}"
    return None


def assess_screening_gaps(ctx: EcmContext) -> EcmContext:
    """Populate gap arrays from missing nameplate / tariff / fan evidence."""
    out = ctx
    for asset in out.assets:
        if asset.kind in (AssetKind.SUPPLY_FAN, AssetKind.RETURN_FAN, AssetKind.MOTOR):
            if "hp" not in asset.nameplate and "kw" not in asset.nameplate:
                out.missing_evidence.append(
                    GapItem(
                        code="missing_nameplate_power",
                        message=f"{asset.asset_id}: no nameplate hp/kW",
                        severity="blocking",
                        asset_id=asset.asset_id,
                        recommended_action="Capture nameplate or TAB motor hp",
                    )
                )
                out.blocking_issues.append(
                    GapItem(
                        code="rebate_blocked_nameplate",
                        message="Rebate-ready fan ECM blocked without nameplate power",
                        severity="blocking",
                        asset_id=asset.asset_id,
                    )
                )
                out.assumptions_required.append(
                    GapItem(
                        code="assume_nameplate_power",
                        message="Screening may proceed only with documented hp/kW assumption",
                        severity="warning",
                        asset_id=asset.asset_id,
                    )
                )
                out.recommended_measurements.append(
                    GapItem(
                        code="measure_nameplate",
                        message="Photograph nameplate or pull TAB rated hp",
                        asset_id=asset.asset_id,
                    )
                )
    if out.tariff.energy_rate is None and out.tariff.demand_rate is None:
        out.tariff.monetary_available = False
        out.missing_evidence.append(
            GapItem(
                code="missing_tariff",
                message="No energy/demand rate — monetary results UNAVAILABLE",
                severity="warning",
                recommended_action="Attach utility tariff or mark assumption",
            )
        )
        out.assumptions_required.append(
            GapItem(
                code="assume_tariff",
                message="Do not invent client tariff; leave $ UNAVAILABLE or label assumption",
                severity="warning",
            )
        )
    return out


def combine_schedule_then_fan_reset(
    *,
    equipment_kw: float,
    baseline_annual_hours: float,
    proposed_annual_hours: float,
    design_kw: float,
    baseline_speed_fraction: float,
    proposed_speed_fraction: float,
    average_load_fraction: float = 1.0,
    power_exponent: float = 3.0,
) -> dict[str, Any]:
    """Apply schedule first, then fan affinity on remaining runtime (no double count).

    Summing standalone schedule + standalone fan_affinity savings is incorrect when
    both apply to the same end-use hours.
    """
    from .algorithms import calculate

    sched = calculate(
        "schedule_reduction",
        {
            "equipment_kw": equipment_kw,
            "baseline_annual_hours": baseline_annual_hours,
            "proposed_annual_hours": proposed_annual_hours,
            "average_load_fraction": average_load_fraction,
        },
    )
    remaining_hours = max(0.0, float(proposed_annual_hours))
    fan = calculate(
        "fan_affinity",
        {
            "design_kw": design_kw,
            "hours": remaining_hours,
            "baseline_speed_fraction": baseline_speed_fraction,
            "proposed_speed_fraction": proposed_speed_fraction,
            "power_exponent": power_exponent,
        },
    )
    naive_fan = calculate(
        "fan_affinity",
        {
            "design_kw": design_kw,
            "hours": baseline_annual_hours,
            "baseline_speed_fraction": baseline_speed_fraction,
            "proposed_speed_fraction": proposed_speed_fraction,
            "power_exponent": power_exponent,
        },
    )
    combined = float(sched["savings_kwh"]) + float(fan["savings_kwh"])
    naive_sum = float(sched["savings_kwh"]) + float(naive_fan["savings_kwh"])
    return {
        "schedule": sched,
        "fan_on_remaining_hours": fan,
        "fan_on_baseline_hours_naive": naive_fan,
        "combined_savings_kwh": combined,
        "naive_sum_savings_kwh": naive_sum,
        "double_count_delta_kwh": naive_sum - combined,
        "method": "schedule_then_fan_remaining_runtime",
        "interaction_status": InteractionStatus.ESTIMATED.value,
    }


__all__ = [
    "ECM_CONTEXT_SCHEMA_VERSION",
    "ReadinessStatus",
    "AssetKind",
    "PointProvenance",
    "EquipmentAsset",
    "RoleQuality",
    "BaselineMetric",
    "TariffContext",
    "EcmScenario",
    "CalcResult",
    "MeasureInteraction",
    "GapItem",
    "EcmContext",
    "ecm_context_from_dict",
    "validate_ecm_context",
    "reject_incompatible_units",
    "assess_screening_gaps",
    "combine_schedule_then_fan_reset",
]
