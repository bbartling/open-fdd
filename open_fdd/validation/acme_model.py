"""ACME live-site commissioning model validation (fixture regression)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ACME_SITE_ID = "acme"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "workspace" / "data" / "fixtures" / "acme_data_model.json"

REQUIRED_RULE_IDS = (
    "acme-sat-flatline-1h",
    "acme-ahu-afterhours-runtime",
    "acme-oat-vs-web-spread",
    "acme-vav-airflow-low",
    "acme-vav-damper-stuck",
    "acme-zn-t-oob-occupied",
    "acme-zn-t-flatline-1h",
)

ROUND_TRIP_POINT_KEYS = (
    "id",
    "site_id",
    "equipment_id",
    "brick_type",
    "fdd_input",
    "external_id",
    "metadata",
    "fdd_rule_ids",
)


@dataclass
class AcmeModelReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    site_id: str = ""
    equipment_counts: dict[str, int] = field(default_factory=dict)
    point_count: int = 0
    brick_type_counts: dict[str, int] = field(default_factory=dict)
    rule_ids: list[str] = field(default_factory=list)
    rules_with_bindings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "site_id": self.site_id,
            "equipment_counts": self.equipment_counts,
            "point_count": self.point_count,
            "brick_type_counts": self.brick_type_counts,
            "rule_ids": self.rule_ids,
            "rules_with_bindings": self.rules_with_bindings,
        }


def load_acme_model(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_FIXTURE
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ACME model root must be a JSON object")
    return data


def validate_acme_model(model: dict[str, Any]) -> AcmeModelReport:
    report = AcmeModelReport()
    sites = [s for s in model.get("sites") or [] if isinstance(s, dict)]
    site_ids = {str(s.get("id") or "").strip() for s in sites}
    if site_ids != {ACME_SITE_ID}:
        report.errors.append(f"expected exactly one site {ACME_SITE_ID!r}, got {sorted(site_ids)}")
        report.ok = False

    equipment = [e for e in model.get("equipment") or [] if isinstance(e, dict)]
    equip_by_id = {str(e.get("id") or "").strip(): e for e in equipment if str(e.get("id") or "").strip()}
    brick_counts: dict[str, int] = {}
    for eq in equipment:
        bt = str(eq.get("brick_type") or "").strip() or "unknown"
        brick_counts[bt] = brick_counts.get(bt, 0) + 1
    report.equipment_counts = brick_counts

    if not any(str(e.get("brick_type") or "") == "AHU" for e in equipment):
        report.errors.append("missing AHU/RTU equipment (brick_type AHU)")
        report.ok = False
    if brick_counts.get("Hot_Water_Plant", 0) < 1:
        report.errors.append("missing Hot_Water_Plant equipment")
        report.ok = False
    if brick_counts.get("Building_Supervisor", 0) < 1:
        report.errors.append("missing Building_Supervisor equipment")
        report.ok = False
    if brick_counts.get("VAV", 0) < 1:
        report.errors.append("missing VAV equipment")
        report.ok = False

    points = [p for p in model.get("points") or [] if isinstance(p, dict)]
    report.point_count = len(points)
    pt_brick: dict[str, int] = {}
    for pt in points:
        bt = str(pt.get("brick_type") or "").strip() or "unknown"
        pt_brick[bt] = pt_brick.get(bt, 0) + 1
    report.brick_type_counts = pt_brick

    for pt in points:
        pid = str(pt.get("id") or "").strip()
        if not pid:
            report.errors.append("point missing id")
            report.ok = False
            continue
        sid = str(pt.get("site_id") or "").strip()
        if sid != ACME_SITE_ID:
            report.errors.append(f"point {pid}: site_id must be {ACME_SITE_ID!r}")
            report.ok = False
        eid = str(pt.get("equipment_id") or "").strip()
        if not eid or eid not in equip_by_id:
            report.errors.append(f"point {pid}: orphan or missing equipment_id {eid!r}")
            report.ok = False
        if not str(pt.get("brick_type") or "").strip():
            report.errors.append(f"point {pid}: missing brick_type")
            report.ok = False
        if not str(pt.get("fdd_input") or "").strip():
            report.errors.append(f"point {pid}: missing fdd_input")
            report.ok = False
        meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
        if not str(meta.get("series_id") or "").strip():
            report.errors.append(f"point {pid}: missing metadata.series_id")
            report.ok = False
        if not str(meta.get("external_ref") or "").strip():
            report.errors.append(f"point {pid}: missing metadata.external_ref")
            report.ok = False

    for eid, eq in equip_by_id.items():
        if not any(str(p.get("equipment_id") or "") == eid for p in points):
            report.warnings.append(f"equipment {eid!r} has no points")

    rules = [r for r in model.get("fdd_rules") or [] if isinstance(r, dict)]
    rule_ids = {str(r.get("id") or "").strip() for r in rules if str(r.get("id") or "").strip()}
    report.rule_ids = sorted(rule_ids)
    report.rules_with_bindings = sum(1 for r in rules if isinstance(r.get("bindings"), dict))

    for rid in REQUIRED_RULE_IDS:
        if rid not in rule_ids:
            report.errors.append(f"required fdd_rule missing: {rid}")
            report.ok = False

    for pt in points:
        pid = str(pt.get("id") or "").strip()
        for rid in pt.get("fdd_rule_ids") or []:
            rs = str(rid).strip()
            if rs and rs not in rule_ids:
                report.errors.append(f"point {pid}: fdd_rule_ids references unknown rule {rs!r}")
                report.ok = False

    for rule in rules:
        bindings = rule.get("bindings") if isinstance(rule.get("bindings"), dict) else {}
        for key in ("point_ids", "equipment_ids"):
            for ref in bindings.get(key) or []:
                ref_s = str(ref).strip()
                if not ref_s:
                    continue
                if key == "point_ids" and ref_s not in {str(p.get("id") or "") for p in points}:
                    report.warnings.append(f"rule {rule.get('id')}: binding point {ref_s!r} not in model")
                if key == "equipment_ids" and ref_s not in equip_by_id:
                    report.warnings.append(f"rule {rule.get('id')}: binding equipment {ref_s!r} not in model")

    return report


def round_trip_preserves_model_fields(model: dict[str, Any]) -> list[str]:
    """JSON serialize/parse must preserve point IDs, bindings, and historian metadata."""
    errors: list[str] = []
    restored = json.loads(json.dumps(model))
    orig_points = {str(p.get("id")): p for p in model.get("points") or [] if isinstance(p, dict) and p.get("id")}
    new_points = {str(p.get("id")): p for p in restored.get("points") or [] if isinstance(p, dict) and p.get("id")}
    if set(orig_points) != set(new_points):
        errors.append("round-trip changed point id set")
        return errors

    for pid, orig in orig_points.items():
        new = new_points[pid]
        for key in ROUND_TRIP_POINT_KEYS:
            if orig.get(key) != new.get(key):
                errors.append(f"point {pid}: round-trip changed {key}")
        meta_o = orig.get("metadata") if isinstance(orig.get("metadata"), dict) else {}
        meta_n = new.get("metadata") if isinstance(new.get("metadata"), dict) else {}
        if meta_o.get("series_id") != meta_n.get("series_id"):
            errors.append(f"point {pid}: round-trip changed metadata.series_id")

    orig_equip = {str(e.get("id")): e for e in model.get("equipment") or [] if isinstance(e, dict) and e.get("id")}
    new_equip = {str(e.get("id")): e for e in restored.get("equipment") or [] if isinstance(e, dict) and e.get("id")}
    if set(orig_equip) != set(new_equip):
        errors.append("round-trip changed equipment id set")

    orig_rules = model.get("fdd_rules") or []
    new_rules = restored.get("fdd_rules") or []
    if len(orig_rules) != len(new_rules):
        errors.append("round-trip changed fdd_rules count")
    else:
        for o, n in zip(orig_rules, new_rules):
            if str(o.get("id") or "") != str(n.get("id") or ""):
                errors.append("round-trip reordered or altered fdd_rule ids")
                break
            if o.get("bindings") != n.get("bindings"):
                errors.append(f"rule {o.get('id')}: round-trip changed bindings")

    return errors


def summarize_acme_model(model: dict[str, Any], report: AcmeModelReport | None = None) -> str:
    rep = report or validate_acme_model(model)
    lines = [
        f"ACME model summary (site={ACME_SITE_ID})",
        f"  points: {rep.point_count}",
        f"  equipment: {sum(rep.equipment_counts.values())} ({', '.join(f'{k}={v}' for k, v in sorted(rep.equipment_counts.items()))})",
        f"  fdd_rules: {len(rep.rule_ids)} ({rep.rules_with_bindings} with bindings)",
        f"  top point brick types: {', '.join(f'{k}={v}' for k, v in sorted(rep.brick_type_counts.items(), key=lambda x: -x[1])[:8])}",
    ]
    if rep.warnings:
        lines.append("  warnings:")
        lines.extend(f"    - {w}" for w in rep.warnings[:10])
    if rep.errors:
        lines.append("  errors:")
        lines.extend(f"    - {e}" for e in rep.errors[:20])
    else:
        lines.append("  validation: OK")
    lines.append("  follow-ups: re-export after BACnet discover; dry-run commissioning-import before apply; no secrets in exports")
    return "\n".join(lines)
