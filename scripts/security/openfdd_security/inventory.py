"""Route inventory load + CI coverage detection."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


INVENTORY_PATH = (
    Path(__file__).resolve().parents[1] / "inventory" / "routes.json"
)


def load_inventory(path: Path | None = None) -> dict[str, Any]:
    p = path or INVENTORY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def inventory_summary(inv: dict[str, Any]) -> dict[str, Any]:
    routes = inv.get("routes") or []
    covered = [r for r in routes if r.get("disposition") == "COVERED"]
    blocked = [r for r in routes if r.get("disposition") == "BLOCKED_POLICY"]
    return {
        "route_count": len(routes),
        "covered": len(covered),
        "blocked_policy": len(blocked),
        "denominator": len(routes),
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
    # Limit to router construction region
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
