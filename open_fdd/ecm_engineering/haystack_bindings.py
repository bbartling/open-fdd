"""Adapt central ``ofdd_haystack_typed_bindings_v1`` / ECM consumer plans.

Python stays on PyPI (offline/agent). Does not invent tariffs or fetch URLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ADAPTER_VERSION = "haystack_ecm_bindings_v1"


@dataclass
class BindingAdaptResult:
    ok: bool
    assets: list[dict[str, Any]] = field(default_factory=list)
    missing_units: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    adapter_version: str = ADAPTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "adapter_version": self.adapter_version,
            "assets": self.assets,
            "missing_units": self.missing_units,
            "blocking_issues": self.blocking_issues,
        }


def adapt_typed_bindings(payload: dict[str, Any]) -> BindingAdaptResult:
    """Consume ECM consumer plan or raw typed binding set from central.

    Accepts either:
    - ``POST /api/model/sparql/consumers`` bundle (uses ``ecm`` key), or
    - ``ofdd_haystack_ecm_binding_plan_v1`` document directly.
    """
    issues: list[str] = []
    if not isinstance(payload, dict):
        return BindingAdaptResult(ok=False, blocking_issues=["payload must be an object"])

    ecm = payload.get("ecm") if isinstance(payload.get("ecm"), dict) else payload
    schema = ecm.get("schema")
    if schema not in (
        "ofdd_haystack_ecm_binding_plan_v1",
        "ofdd_haystack_typed_bindings_v1",
    ) and "assets" not in ecm and "equipment" not in ecm:
        issues.append(f"unexpected schema: {schema!r}")

    assets_in = ecm.get("assets")
    if assets_in is None and isinstance(ecm.get("equipment"), list):
        # Raw typed bindings → synthesize asset view.
        assets_in = []
        for eq in ecm["equipment"]:
            if not isinstance(eq, dict):
                continue
            assets_in.append(
                {
                    "equipment_id": eq.get("equipment_id"),
                    "equip_type": eq.get("equip_type"),
                    "points": eq.get("points") or [],
                }
            )

    if not isinstance(assets_in, list):
        return BindingAdaptResult(
            ok=False, blocking_issues=issues + ["assets/equipment list required"]
        )

    assets: list[dict[str, Any]] = []
    missing_units: list[str] = []
    for asset in assets_in:
        if not isinstance(asset, dict):
            continue
        eid = asset.get("equipment_id")
        if not eid:
            issues.append("asset missing equipment_id")
            continue
        points_out: list[dict[str, Any]] = []
        for pt in asset.get("points") or []:
            if not isinstance(pt, dict):
                continue
            unit = pt.get("unit")
            col = pt.get("column") or pt.get("point_id") or "?"
            if not unit:
                missing_units.append(f"{eid}.{col}")
            points_out.append(
                {
                    "point_id": pt.get("point_id"),
                    "column": pt.get("column"),
                    "canonical_role": pt.get("canonical_role"),
                    "unit": unit,
                    "kind": pt.get("kind"),
                    "fdd_ready": bool(pt.get("fdd_ready")),
                }
            )
        assets.append(
            {
                "equipment_id": eid,
                "equip_type": asset.get("equip_type"),
                "points": points_out,
            }
        )

    ok = not issues and bool(assets)
    return BindingAdaptResult(
        ok=ok,
        assets=assets,
        missing_units=missing_units,
        blocking_issues=issues,
    )
