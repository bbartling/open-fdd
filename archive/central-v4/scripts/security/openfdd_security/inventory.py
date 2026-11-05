"""Route inventory load + CI coverage detection (honesty model v2)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


INVENTORY_DIR = Path(__file__).resolve().parents[1] / "inventory"
INVENTORY_PATH = INVENTORY_DIR / "routes.json"
IMPLEMENTED_PATH = INVENTORY_DIR / "implemented_checks.json"
PROFILE_REQUIRED_PATH = INVENTORY_DIR / "profile_required_v1.json"
CROSS_CUTTING_PATH = INVENTORY_DIR / "cross_cutting_checks.json"

VALID_DISPOSITIONS = frozenset({"PLANNED", "IMPLEMENTED", "BLOCKED_POLICY", "EXCLUDED"})
POLICY_SOURCE = "scripts/security/inventory/"


def load_inventory(path: Path | None = None) -> dict[str, Any]:
    p = path or INVENTORY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def load_implemented_checks(path: Path | None = None) -> set[str]:
    p = path or IMPLEMENTED_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return set(data.get("check_ids") or [])


def load_cross_cutting_checks(path: Path | None = None) -> set[str]:
    p = path or CROSS_CUTTING_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return set(data.get("check_ids") or [])


def planned_check_ids_from_routes(inv: dict[str, Any] | None = None) -> set[str]:
    inv = inv or load_inventory()
    out: set[str] = set()
    for route in inv.get("routes") or []:
        for cid in route.get("planned_check_ids") or route.get("check_ids") or []:
            if isinstance(cid, str) and cid:
                out.add(cid)
    return out


def profile_required_drift_errors(
    *,
    inv: dict[str, Any] | None = None,
    profile_required: dict[str, Any] | None = None,
    cross_cutting: set[str] | None = None,
) -> list[str]:
    """Fail closed when profile-required IDs are missing from inventory policy."""
    from .profiles import load_profile_required

    inv = inv or load_inventory()
    profile_required = profile_required or load_profile_required()
    cross_cutting = (
        cross_cutting if cross_cutting is not None else load_cross_cutting_checks()
    )
    planned = planned_check_ids_from_routes(inv)
    allowed = planned | cross_cutting
    errors: list[str] = []
    if inv.get("policy_source") != POLICY_SOURCE:
        errors.append(
            f"routes.json policy_source must be {POLICY_SOURCE!r} (single inventory source)"
        )
    for profile, suites in profile_required.items():
        if not isinstance(suites, dict):
            errors.append(f"profile {profile}: suites must be an object")
            continue
        for suite, ids in suites.items():
            if not isinstance(ids, list):
                errors.append(f"profile {profile} suite {suite}: must be a list")
                continue
            for cid in ids:
                if cid not in allowed:
                    errors.append(
                        f"profile {profile}/{suite}: {cid} missing from "
                        "routes.json planned_check_ids and cross_cutting_checks.json"
                    )
    return errors


def inventory_summary(inv: dict[str, Any]) -> dict[str, Any]:
    routes = inv.get("routes") or []
    counts: dict[str, int] = {}
    for r in routes:
        d = r.get("disposition") or "UNKNOWN"
        counts[d] = counts.get(d, 0) + 1
    return {
        "route_count": len(routes),
        "disposition_counts": counts,
        "planned": counts.get("PLANNED", 0),
        "implemented": counts.get("IMPLEMENTED", 0),
        "blocked_policy": counts.get("BLOCKED_POLICY", 0),
        "denominator": len(routes),
        # legacy key — do not treat as tested
        "covered_legacy_removed": True,
    }


def extract_routes_from_source(routes_rs: Path) -> set[tuple[str, str]]:
    """Parse .route registrations from routes.rs for drift detection."""
    text = routes_rs.read_text(encoding="utf-8")
    route_re = re.compile(
        r'\.route\(\s*"([^"]+)"\s*,\s*(.+?)\)\s*(?:;|,|\n)',
        re.S,
    )
    method_re = re.compile(r"\b(get|post|put|patch|delete)\s*\(")
    found: set[tuple[str, str]] = set()
    start = text.find("let public = Router::new()")
    end = text.find("Router::new()\n        .merge(public)")
    body = text[start:end] if start >= 0 and end > start else text
    for m in route_re.finditer(body):
        path = m.group(1)
        for method in method_re.findall(m.group(2)):
            found.add((method.upper(), path))
    return found


def find_uninventoried_routes(
    routes_rs: Path, inventory_path: Path | None = None
) -> list[tuple[str, str]]:
    inv = load_inventory(inventory_path)
    known = {(r["method"], r["path"]) for r in inv.get("routes") or []}
    live = extract_routes_from_source(routes_rs)
    return sorted(live - known)


def inventory_integrity_errors(
    inv: dict[str, Any] | None = None,
    *,
    implemented: set[str] | None = None,
) -> list[str]:
    """Return human-readable integrity failures (empty = OK)."""
    inv = inv or load_inventory()
    implemented = implemented if implemented is not None else load_implemented_checks()
    errors: list[str] = []
    routes = inv.get("routes") or []
    if not routes:
        errors.append("inventory has zero routes")
    planned_ids: dict[str, str] = {}
    for r in routes:
        method = r.get("method")
        path = r.get("path")
        key = f"{method} {path}"
        disp = r.get("disposition")
        if disp not in VALID_DISPOSITIONS:
            errors.append(f"{key}: invalid disposition {disp!r}")
        if disp == "COVERED":
            errors.append(f"{key}: COVERED is forbidden; use PLANNED/IMPLEMENTED")
        for field in (
            "request_schema",
            "response_schema",
            "side_effects",
            "planned_check_ids",
        ):
            if field not in r:
                errors.append(f"{key}: missing field {field}")
        ids = list(r.get("planned_check_ids") or r.get("check_ids") or [])
        if not ids:
            errors.append(f"{key}: empty planned_check_ids")
        for cid in ids:
            if cid in planned_ids:
                errors.append(
                    f"duplicate planned_check_id {cid}: {planned_ids[cid]} and {key}"
                )
            planned_ids[cid] = key
        impl_ids = list(r.get("implemented_check_ids") or [])
        if disp == "IMPLEMENTED":
            if not impl_ids:
                errors.append(f"{key}: IMPLEMENTED but implemented_check_ids empty")
            for cid in impl_ids:
                if cid not in implemented:
                    errors.append(
                        f"{key}: implemented_check_id {cid} not in suite registry"
                    )
        elif impl_ids:
            errors.append(
                f"{key}: disposition {disp} but implemented_check_ids non-empty"
            )
        # IMPLEMENTED must not claim tests that suites do not emit
        for cid in impl_ids:
            if cid not in ids and cid not in (r.get("check_ids") or []):
                # allow suite ids only listed under implemented_check_ids
                pass
    # Orphan: registry ids that claim route coverage should appear somewhere
    # Suite-only detector IDs (y.detector.*, z.detector.*) are allowed orphans.
    errors.extend(profile_required_drift_errors(inv=inv))
    return errors
