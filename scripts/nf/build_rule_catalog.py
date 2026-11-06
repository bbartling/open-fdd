#!/usr/bin/env python3
"""Build the Open-FDD NF app's rule catalog (nf-app/static/fdd-catalog.json).

Inputs (all in git, no NF needed):
  sql/fdd/registry.yaml            rules: id, required/optional roles, equipment kinds, parameters
  sql/fdd/role_map.json            role -> Haystack-style name (sat -> discharge-air-temp)
  nf-app/rules/nf_classes.json     NF ontology class names (from /api/v1/equipment/classes)
  nf-app/rules/role_overrides.json hand mapping for roles NF names differently

For every role it records the NF classes that fill it and a Haystack marker set used when a
point has no class. The app (static/fdd.js) and the FDD hook match points with exactly this file.

    python3 scripts/nf/build_rule_catalog.py           # write the catalog
    python3 scripts/nf/build_rule_catalog.py --check   # exit 1 if it is out of date (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "nf-app/static/fdd-catalog.json"


def derived_markers(name: str) -> list[str]:
    """discharge-air-temp -> [discharge, air, temp, sensor]; *-sp / *-cmd keep their kind."""
    parts = name.split("-")
    kind = parts[-1] if parts[-1] in ("sp", "cmd", "sensor", "status") else "sensor"
    body = parts[:-1] if parts[-1] in ("sp", "cmd", "sensor", "status") else parts
    return body + ["sensor" if kind == "status" else kind]


def build() -> dict:
    role_map = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))
    classes = set(json.loads((ROOT / "nf-app/rules/nf_classes.json").read_text(encoding="utf-8"))["classes"])
    overrides = json.loads((ROOT / "nf-app/rules/role_overrides.json").read_text(encoding="utf-8"))
    overrides.pop("_doc", None)
    kinds = overrides.pop("_equipment_kinds")
    kinds.pop("_doc", None)
    registry = yaml.safe_load((ROOT / "sql/fdd/registry.yaml").read_text(encoding="utf-8"))

    bad = sorted({c for o in overrides.values() for c in o["classes"] if c not in classes})
    if bad:
        raise SystemExit(f"role_overrides.json names classes NF does not have: {bad}")
    unnamed = sorted(r for r in set(overrides) - set(role_map) if "name" not in overrides[r])
    if unnamed:
        raise SystemExit(f"role_overrides.json roles not in role_map.json need a \"name\": {unnamed}")

    roles = {}
    for role, name in sorted({**role_map, **{r: o["name"] for r, o in overrides.items() if r not in role_map}}.items()):
        if role in overrides:
            roles[role] = {"name": name, **{k: v for k, v in overrides[role].items() if k != "name"}}
        else:
            found = [c for c in (name, f"{name}-sensor", f"{name}-cmd", f"{name}-status") if c in classes]
            roles[role] = {"name": name, "classes": found, "markers": derived_markers(name)}

    rules = []
    for r in registry["rules"]:
        req, opt = r.get("required_roles") or [], r.get("optional_roles") or []
        missing = sorted({x for x in req + opt if x not in roles})
        unknown_kinds = sorted(set(r.get("equipment_kinds") or []) - set(kinds))
        if unknown_kinds:
            raise SystemExit(f"rule {r['rule_id']}: equipment kinds missing from _equipment_kinds: {unknown_kinds}")
        rules.append({
            "id": r["rule_id"],
            "description": r.get("description", ""),
            "sql_file": r.get("sql_file"),
            "priority": r.get("priority"),
            "equipment_kinds": r.get("equipment_kinds") or [],
            "required_roles": req,
            "optional_roles": opt,
            "unmapped_roles": missing,
            "confirm_seconds": r.get("confirm_seconds", 0),
            "parameters": {k: v.get("default") for k, v in (r.get("parameters") or {}).items()},
        })
    return {
        "_generated_by": "scripts/nf/build_rule_catalog.py",
        "source": ["sql/fdd/registry.yaml", "sql/fdd/role_map.json", "nf-app/rules/role_overrides.json"],
        "equipment_kinds": kinds,
        "roles": roles,
        "rules": rules,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if the committed catalog is out of date")
    args = ap.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python3 scripts/nf/build_rule_catalog.py", file=sys.stderr)
            return 1
        print("fdd-catalog.json is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    data = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['roles'])} roles, {len(data['rules'])} rules, "
          f"{sum(1 for r in data['roles'].values() if r['classes'])} roles with NF classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
