"""Generate configs/rule_inventory.yaml and configs/rule_defaults.yaml from cookbook catalog."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.rules.cookbook_catalog import RULES

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"


def main() -> None:
    inventory = []
    defaults: dict = {}
    for r in RULES:
        inventory.append(
            {
                "rule_id": r.id,
                "family": r.family,
                "title": r.title,
                "description": r.equation,
                "summary": r.summary,
                "required_roles": r.required_roles,
                "optional_roles": r.optional_roles,
                "equipment_kinds": r.equipment_kinds,
                "tunable_params": [p.key for p in r.params],
                "default_confirm_seconds": r.confirm_seconds,
                "sensor_sweep": r.sensor_sweep,
                "implemented": True,
                "skipped_if_missing_roles": True,
                "test_coverage": True,
                "output_metrics": ["fault_hours", "fault_pct", "fault_sample_count"],
                "source_function": r.compute.__name__,
                "known_limitations": "ECON-3 uses weather-aware compute in runner.py" if r.id == "ECON-3" else "",
            }
        )
        block: dict = {}
        for p in r.params:
            block[p.key] = {
                "label": p.label,
                "default": p.default,
                "min": p.min,
                "max": p.max,
                "step": p.step,
                "unit": p.unit,
                "direction": getattr(p, "direction", "") or "",
                "help": p.help_text() if hasattr(p, "help_text") else p.label,
            }
        defaults[r.id] = block

    CONFIGS.mkdir(parents=True, exist_ok=True)
    (CONFIGS / "rule_inventory.yaml").write_text(
        yaml.safe_dump({"canonical_rule_count": len(RULES), "rules": inventory}, sort_keys=False),
        encoding="utf-8",
    )
    (CONFIGS / "rule_defaults.yaml").write_text(yaml.safe_dump(defaults, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(RULES)} rules to {CONFIGS}")


if __name__ == "__main__":
    main()
