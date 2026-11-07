"""Adapt Haystack point bindings for ECM work.

Bindings come from a Normal Framework model (``open_fdd.nf.model``: live via ``load_model`` or offline
from the app's Turtle export via ``read_turtle``), or from a plain ``ofdd_haystack_typed_bindings_v1`` /
``ofdd_haystack_ecm_binding_plan_v1`` JSON document. Python stays on PyPI (offline/agent). Does not invent
tariffs or fetch URLs.
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
    """Consume an ECM binding plan or a raw typed binding set (plain JSON).

    Accepts either a bundle whose ``ecm`` key holds the plan, or the
    ``ofdd_haystack_ecm_binding_plan_v1`` / ``ofdd_haystack_typed_bindings_v1`` document directly.
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


def bindings_from_model(model: Any, site: str | None = None) -> dict[str, Any]:
    """Typed bindings (``ofdd_haystack_typed_bindings_v1``) from an ``open_fdd.nf.model.Model``.

    One entry per equipment; one point per FDD role the equipment fills (best match). ``unit`` is the
    point's declared unit, ``canonical_role`` the pandas Haystack role name, ``fdd_ready`` is true when
    the unit can be brought to SI for that role.
    """
    from open_fdd.nf.model import bind_equipment, column_for, si_plan_for

    equipment = []
    for b in bind_equipment(model, site=site):
        points = []
        for role, p in b.best().items():
            points.append({
                "point_id": p.uuid,
                "column": p.dis,
                "canonical_role": column_for(role),
                "unit": p.unit or None,
                "kind": p.kind,
                "fdd_ready": si_plan_for(role, p).convert is not None,
            })
        if points:
            equipment.append({"equipment_id": b.equip, "equip_type": b.stamp or None, "points": points})
    return {"schema": "ofdd_haystack_typed_bindings_v1", "equipment": equipment}


def adapt_nf_model(model: Any, site: str | None = None) -> BindingAdaptResult:
    """ECM assets from a live (``load_model``) or Turtle-derived (``read_turtle``) NF model."""
    return adapt_typed_bindings(bindings_from_model(model, site=site))


def adapt_turtle(path: Any, site: str | None = None) -> BindingAdaptResult:
    """ECM assets from the NF app's RDF/Turtle export (needs the ``rdf`` extra)."""
    from open_fdd.nf.export import read_turtle

    return adapt_nf_model(read_turtle(path), site=site)
