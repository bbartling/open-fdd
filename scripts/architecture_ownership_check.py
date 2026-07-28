#!/usr/bin/env python3
"""Validate openfdd_agent_spec ownership.yaml + required cookbook paths.

Lightweight Milestone A Phase 0 CI smoke — does not replace cookbook_parity_check.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
OWNERSHIP = ROOT / "openfdd_agent_spec" / "ownership.yaml"
COOKBOOK = ROOT / "docs" / "rules" / "cookbook"
REQUIRED_COOKBOOKS = (
    "datafusion-sql-cookbook.md",
    "pandas-cookbook.md",
    "parity-matrix.md",
)


def main() -> int:
    errors: list[str] = []
    if not OWNERSHIP.is_file():
        errors.append(f"missing {OWNERSHIP.relative_to(ROOT)}")
    elif yaml is None:
        # stdlib-only fallback: require non-empty YAML-looking file
        text = OWNERSHIP.read_text(encoding="utf-8")
        if "schema_version:" not in text or "components:" not in text:
            errors.append("ownership.yaml missing required keys (install PyYAML for full parse)")
    else:
        data = yaml.safe_load(OWNERSHIP.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append("ownership.yaml must parse to a mapping")
        else:
            if data.get("schema_version") != 1:
                errors.append(f"unexpected schema_version: {data.get('schema_version')!r}")
            comps = data.get("components")
            if not isinstance(comps, dict):
                errors.append("components must be a mapping")
            else:
                for key in (
                    "pandas_rule_execution",
                    "production_rule_execution",
                    "generic_ecm_math",
                    "cookbooks",
                ):
                    if key not in comps:
                        errors.append(f"components missing {key}")
                future = comps.get("future_concepts")
                if isinstance(future, dict):
                    if future.get("policy") != "never_delete":
                        errors.append("future_concepts.policy must be never_delete")
                elif future is not None:
                    errors.append("future_concepts must be a mapping with paths + policy")

    for name in REQUIRED_COOKBOOKS:
        path = COOKBOOK / name
        if not path.is_file():
            errors.append(f"missing cookbook {path.relative_to(ROOT)}")
        elif path.stat().st_size < 200:
            errors.append(f"cookbook suspiciously small: {path.relative_to(ROOT)}")

    if errors:
        print("architecture_ownership_check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("architecture_ownership_check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
