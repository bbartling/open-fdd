#!/usr/bin/env python3
"""Validate openfdd_agent_spec ownership.yaml + required cookbook paths + README invariants.

Lightweight Milestone A/C0 CI smoke — does not replace cookbook_parity_check.
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
OWNERSHIP = ROOT / "openfdd_agent_spec" / "ownership.yaml"
README = ROOT / "README.md"
COOKBOOK = ROOT / "docs" / "rules" / "cookbook"
REQUIRED_COOKBOOKS = (
    "datafusion-sql-cookbook.md",
    "pandas-cookbook.md",
    "parity-matrix.md",
)

# Dual cookbooks are large expression catalogs — reject vibe-coded stubs.
COOKBOOK_MIN_BYTES = {
    "datafusion-sql-cookbook.md": 40_000,
    "pandas-cookbook.md": 40_000,
    "parity-matrix.md": 1_500,
}

# README navigation / product wording invariants (C0).
README_REQUIRED_MARKERS = (
    "FDD Rule Cookbook",
    "pypi.org/project/open-fdd",
    "Apache DataFusion",
    "Apache Arrow",
    "datafusion-sql-cookbook",
    "pandas-cookbook",
    "img.shields.io/badge/Docs-online",
    "FDD%20Rule%20Cookbook",
    "img.shields.io/pypi/v/open-fdd",
    "Quick%20Start-GHCR%20stack",
    "Apache%20Arrow-columnar%20data",
    "DataFusion-SQL%20engine",
)


def _check_readme(errors: list[str]) -> None:
    if not README.is_file():
        errors.append("missing README.md")
        return
    text = README.read_text(encoding="utf-8")
    for marker in README_REQUIRED_MARKERS:
        if marker not in text:
            errors.append(f"README.md missing required marker: {marker!r}")
    # Forbidden production-UI claims
    if "Vite :5173" in text or "Vite/Caddy SPA" in text and "not a Vite" not in text:
        # Allow explicit negation ("not a Vite/Caddy SPA") but not the old develop hint.
        if "Vite :5173" in text:
            errors.append("README.md must not claim Vite :5173 as the UI develop path")
    if "59" not in text or "63" not in text:
        errors.append(
            "README.md must state both public cookbook 59 and SQL registry 63 (count contract)"
        )
    if "React" not in text and "openfdd-web" not in text:
        errors.append("README.md must identify React (openfdd-web) as the operator UI")
    if "Streamlit" in text and "not Streamlit" not in text and "Streamlit product removed" not in text:
        # Allow explicit negation / archive notes only.
        if re.search(r"(?i)production operator UI is \*\*Streamlit\*\*", text) or re.search(
            r"(?i)Streamlit UI for CSV", text
        ):
            errors.append("README.md must not claim Streamlit as the production operator UI")
    if "GHCR" not in text and "ghcr.io" not in text:
        errors.append("README.md must mention GHCR stack for production DataFusion FDD")


def main() -> int:
    errors: list[str] = []
    if not OWNERSHIP.is_file():
        errors.append(f"missing {OWNERSHIP.relative_to(ROOT)}")
    elif yaml is None:
        text = OWNERSHIP.read_text(encoding="utf-8")
        if "schema_version:" not in text or "components:" not in text:
            errors.append("ownership.yaml missing required keys (install PyYAML for full parse)")
        if "protected_docs:" not in text:
            errors.append("ownership.yaml missing protected_docs (install PyYAML for full parse)")
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

            protected = data.get("protected_docs")
            if not isinstance(protected, dict):
                errors.append("protected_docs must be a mapping")
            else:
                for key in (
                    "root_readme_navigation",
                    "pandas_cookbook",
                    "sql_cookbook",
                    "parity_matrix",
                ):
                    if key not in protected:
                        errors.append(f"protected_docs missing {key}")
                nav = protected.get("root_readme_navigation") or {}
                if isinstance(nav, dict):
                    markers = nav.get("required_markers") or []
                    if not isinstance(markers, list) or len(markers) < 4:
                        errors.append(
                            "protected_docs.root_readme_navigation.required_markers incomplete"
                        )

    for name in REQUIRED_COOKBOOKS:
        path = COOKBOOK / name
        if not path.is_file():
            errors.append(f"missing cookbook {path.relative_to(ROOT)}")
            continue
        size = path.stat().st_size
        floor = COOKBOOK_MIN_BYTES.get(name, 200)
        if size < floor:
            errors.append(
                f"cookbook too small (docs fortress): {path.relative_to(ROOT)} "
                f"has {size} bytes, need >= {floor}"
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        if name.endswith("cookbook.md"):
            if "required" not in text.lower() and "Required" not in text:
                errors.append(f"{name}: missing required-roles style content")
            if text.count("#") < 20:
                errors.append(f"{name}: too few markdown headings (catalog must not shrink)")
        if name == "parity-matrix.md":
            if "59" not in text or "63" not in text:
                errors.append("parity-matrix.md must state cookbook 59 and registry 63")

    _check_readme(errors)

    if errors:
        print("architecture_ownership_check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("architecture_ownership_check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
