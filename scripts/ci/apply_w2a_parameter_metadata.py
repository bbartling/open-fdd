#!/usr/bin/env python3
"""One-shot W2a metadata: registry kind lines + tuning_catalog kind/effect."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    REGISTRY,
    TUNING,
    apply_tuning_catalog,
    inject_registry_kinds,
    load_json,
)


def main() -> int:
    reg_text = REGISTRY.read_text(encoding="utf-8")
    REGISTRY.write_text(inject_registry_kinds(reg_text), encoding="utf-8")
    tuning = load_json(TUNING)
    updated = apply_tuning_catalog(tuning)
    TUNING.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print("OK: registry kinds + tuning_catalog kind/effect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
