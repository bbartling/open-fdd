#!/usr/bin/env python3
"""Refresh rules_store.json code/backend from workspace/data/rules_py/*.py sources."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.rule_source import read_source  # noqa: E402
from open_fdd.arrow_runtime.rules import detect_rule_backend  # noqa: E402

STORE = REPO / "workspace" / "data" / "rules_store.json"
RULES_PY = REPO / "workspace" / "data" / "rules_py"


def main() -> int:
    data = json.loads(STORE.read_text(encoding="utf-8"))
    updated = 0
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        path = str(rule.get("source_path") or "").strip()
        code = ""
        if path:
            code = read_source(path)
        if not code.strip():
            fname = RULES_PY / f"{rule.get('id', '').replace('-', '_')}.py"
            if fname.is_file():
                code = fname.read_text(encoding="utf-8")
        if not code.strip():
            continue
        backend = detect_rule_backend(code, rule)
        rule["code"] = code
        rule["backend"] = backend if backend != "script" else ""
        updated += 1
    STORE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {updated} rule(s) in {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
