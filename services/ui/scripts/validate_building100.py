"""BUILDING_100 batch validation for Streamlit cookbook rules."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from app.config import AppConfig
from app.data_loader import load_building_tree
from app.role_map import apply_role_map, enrich_role_map_from_equipment, load_role_map
from app.rules.runner import run_all_cookbook_rules
from app.rules import CANONICAL_RULE_COUNT
from app.cache import cached_weather


def validate_building100(data_root: Path | None = None, building_id: str = "BUILDING_100") -> dict:
    cfg = AppConfig.load()
    root = data_root or cfg.data_root
    role_map = load_role_map(cfg.role_map_path)
    tree = load_building_tree(root, building_id)
    for eq_id, raw_df in tree.items():
        cols_path = raw_df.attrs.get("columns_path")
        enrich_role_map_from_equipment(
            role_map,
            eq_id,
            Path(cols_path) if cols_path else None,
            list(raw_df.columns),
        )
    weather = cached_weather(str(root), cfg.weather_subdir)

    status_counts: Counter = Counter()
    missing_role_counts: Counter = Counter()
    all_results = []

    for eq_id, raw_df in tree.items():
        mapped = apply_role_map(raw_df, eq_id, role_map)
        poll = float(raw_df.attrs.get("poll_seconds", 300))
        results = run_all_cookbook_rules(
            mapped,
            equipment_id=eq_id,
            poll_seconds=poll,
            params_by_rule={},
            weather=weather,
        )
        all_results.extend(results)
        for r in results:
            status_counts[r.status] += 1
            for m in r.missing_roles:
                missing_role_counts[m] += 1

    top_faults = sorted(
        [r for r in all_results if r.status == "FAULT"],
        key=lambda x: x.fault_hours or 0,
        reverse=True,
    )[:15]

    return {
        "building_id": building_id,
        "equipment_count": len(tree),
        "canonical_rules": CANONICAL_RULE_COUNT,
        "total_evaluations": len(all_results),
        "pass": status_counts.get("PASS", 0),
        "fault": status_counts.get("FAULT", 0),
        "skipped": status_counts.get("SKIPPED_MISSING_ROLES", 0),
        "not_applicable": status_counts.get("NOT_APPLICABLE_EQUIPMENT_TYPE", 0),
        "error": status_counts.get("ERROR", 0),
        "top_missing_roles": missing_role_counts.most_common(15),
        "top_faults": [
            {"rule_id": r.rule_id, "equipment_id": r.equipment_id, "fault_hours": r.fault_hours}
            for r in top_faults
        ],
    }


def write_validation_doc(out_path: Path) -> dict:
    stats = validate_building100()
    lines = [
        "# BUILDING_100 Streamlit rule validation",
        "",
        f"- Building: **{stats['building_id']}**",
        f"- Equipment: **{stats['equipment_count']}**",
        f"- Canonical rules: **{stats['canonical_rules']}**",
        f"- Total rule/equipment evaluations: **{stats['total_evaluations']}**",
        "",
        "## Status counts",
        "",
        f"| Status | Count |",
        f"| --- | ---: |",
        f"| PASS | {stats['pass']} |",
        f"| FAULT | {stats['fault']} |",
        f"| SKIPPED_MISSING_ROLES | {stats['skipped']} |",
        f"| NOT_APPLICABLE_EQUIPMENT_TYPE | {stats['not_applicable']} |",
        f"| ERROR | {stats['error']} |",
        "",
        "## Top missing roles",
        "",
    ]
    for role, n in stats["top_missing_roles"]:
        lines.append(f"- `{role}`: {n}")
    lines.extend(["", "## Top faults", ""])
    for f in stats["top_faults"]:
        lines.append(f"- **{f['rule_id']}** / {f['equipment_id']}: {f['fault_hours']}h")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Role map YAML covers demo equipment; many VAV/plant rules skip until roles are mapped.",
            "- OAT-METEO / ECON-3 need weather columns merged from `weather/history_wide.csv`.",
            "- Equipment kind inference is heuristic (AHU/VAV/chiller/boiler/weather).",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    (out_path.parent / "building100_validation.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


if __name__ == "__main__":
    APP_ROOT = Path(__file__).resolve().parent.parent
    s = write_validation_doc(APP_ROOT / "docs" / "BUILDING_100_STREAMLIT_RULE_VALIDATION.md")
    print(json.dumps(s, indent=2))
