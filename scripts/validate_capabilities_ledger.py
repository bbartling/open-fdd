#!/usr/bin/env python3
"""Validate docs/migration/react-rust/capabilities.yaml (P1-M0 ledger).

Rejects:
  - QUALIFIED without evidence paths
  - WAIVED without reason/approver/expiry
  - react_route not present in frontend/web/src/App.tsx
  - QUALIFIED capabilities that are demo_only or mention stub/demo/sample
    without an explicit demo_only classification at lower status
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "migration" / "react-rust" / "capabilities.yaml"
APP_TSX = ROOT / "frontend" / "web" / "src" / "App.tsx"

ALLOWED_STATUS = {
    "NOT_STARTED",
    "SCAFFOLD",
    "IMPLEMENTED",
    "VERIFIED",
    "QUALIFIED",
    "WAIVED",
}

STUB_RE = re.compile(r"\b(stub|demo|sample)\b", re.IGNORECASE)


def _parse_app_routes(text: str) -> set[str]:
    routes = set(re.findall(r'path="([^"]+)"', text))
    # Home is "/" — also accept empty string variants as "/"
    if "/" not in routes and 'path="/"' not in text:
        # App.tsx uses path="/" for HomePage
        pass
    return routes


def _evidence_nonempty(ev: object) -> bool:
    if not isinstance(ev, dict) or not ev:
        return False
    for v in ev.values():
        if isinstance(v, list) and v:
            return True
        if isinstance(v, str) and v.strip():
            return True
    return False


def main() -> int:
    errors: list[str] = []
    if not LEDGER.is_file():
        print(f"FAIL: missing {LEDGER.relative_to(ROOT)}", file=sys.stderr)
        return 1
    if yaml is None:
        print("FAIL: PyYAML required (pip install PyYAML)", file=sys.stderr)
        return 1

    data = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("FAIL: ledger root must be a mapping", file=sys.stderr)
        return 1
    caps = data.get("capabilities")
    if not isinstance(caps, list) or not caps:
        errors.append("capabilities must be a non-empty list")
        caps = []

    app_text = APP_TSX.read_text(encoding="utf-8") if APP_TSX.is_file() else ""
    if not app_text:
        errors.append(f"missing {APP_TSX.relative_to(ROOT)}")
    routes = _parse_app_routes(app_text)

    seen_ids: set[str] = set()
    for i, cap in enumerate(caps):
        if not isinstance(cap, dict):
            errors.append(f"capabilities[{i}] must be a mapping")
            continue
        cid = cap.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"capabilities[{i}] missing id")
            continue
        if cid in seen_ids:
            errors.append(f"duplicate capability id {cid}")
        seen_ids.add(cid)

        status = cap.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(f"{cid}: invalid status {status!r}")

        route = cap.get("react_route")
        if route is not None and route != "":
            if not isinstance(route, str):
                errors.append(f"{cid}: react_route must be string or null")
            elif route not in routes:
                errors.append(
                    f"{cid}: react_route {route!r} not found in App.tsx routes {sorted(routes)}"
                )

        apis = cap.get("central_apis") or []
        if not isinstance(apis, list):
            errors.append(f"{cid}: central_apis must be a list")
        else:
            for api in apis:
                if not isinstance(api, str) or not api.startswith("/api/"):
                    errors.append(f"{cid}: central_api must start with /api/: {api!r}")

        evidence = cap.get("evidence") or {}
        demo_only = bool(cap.get("demo_only"))
        limitations = cap.get("limitations") or []
        lim_text = " ".join(str(x) for x in limitations) if isinstance(limitations, list) else str(limitations)

        if status == "QUALIFIED":
            if not _evidence_nonempty(evidence):
                errors.append(f"{cid}: QUALIFIED requires non-empty evidence paths")
            if demo_only:
                errors.append(f"{cid}: QUALIFIED cannot be demo_only")
            if STUB_RE.search(lim_text):
                errors.append(
                    f"{cid}: QUALIFIED limitations mention stub/demo/sample — demote status"
                )

        if status == "WAIVED":
            for key in ("waiver_reason", "waiver_approver", "waiver_expiry"):
                if not cap.get(key):
                    errors.append(f"{cid}: WAIVED requires {key}")

        # Known product honesty: SCAFFOLD/demo capabilities should flag demo_only
        # when limitations mention demo/stub (soft warning as error for recovery).
        if status in {"IMPLEMENTED", "VERIFIED", "QUALIFIED"} and demo_only:
            errors.append(f"{cid}: demo_only=true requires status SCAFFOLD or lower")

    # Required core routes present in ledger
    required_routes = {"/", "/auth", "/jobs", "/upload", "/mapping", "/rules", "/findings", "/reports", "/metering", "/export"}
    ledger_routes = {
        c.get("react_route")
        for c in caps
        if isinstance(c, dict) and c.get("react_route")
    }
    for r in required_routes:
        if r not in routes:
            errors.append(f"App.tsx missing expected product route {r!r}")
        if r not in ledger_routes:
            errors.append(f"ledger missing capability covering react_route {r!r}")

    if errors:
        print("FAIL: capability ledger validation")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"PASS: capabilities.yaml ({len(caps)} capabilities, "
        f"{len(routes)} App.tsx routes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
