#!/usr/bin/env python3
"""Validate Acme FDD bundle: model dedupe, Trane metric profiles, rule lint, optional batch report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))
sys.path.insert(0, str(REPO / "scripts"))

from openfdd_bridge.playground import lint_python  # noqa: E402
from setup_gl36_fdd import RULES_PY, gl36_rule_specs, rule_id_prefix  # noqa: E402
from lib.site_pack_paths import equipment_id  # noqa: E402


def _read(name: str) -> str:
    return (RULES_PY / name).read_text(encoding="utf-8")


def audit_model(model_path: Path) -> dict:
    model = json.loads(model_path.read_text(encoding="utf-8"))
    equipment = model.get("equipment") or []
    points = model.get("points") or []
    dev_ids = [e.get("bacnet_device_id") for e in equipment if e.get("bacnet_device_id") is not None]
    dup_dev = {k: v for k, v in Counter(dev_ids).items() if v > 1}
    pid = Counter(str(p.get("id")) for p in points if p.get("id"))
    dup_pid = {k: v for k, v in pid.items() if v > 1}
    trane = [e for e in equipment if int(e.get("bacnet_device_id") or 0) >= 11000]
    return {
        "equipment_count": len(equipment),
        "point_count": len(points),
        "duplicate_bacnet_device_ids": dup_dev,
        "duplicate_point_ids": dup_pid,
        "trane_vav_count": len(trane),
        "ok": not dup_dev and not dup_pid,
    }


def audit_poll_profiles(profiles_path: Path) -> dict:
    text = profiles_path.read_text(encoding="utf-8").strip().splitlines()
    rows = [line for line in text[1:] if line.strip()]
    trane_rows = [r for r in rows if "metric_temp_f" in r]
    return {
        "profile_rows": len(rows),
        "trane_metric_temp_f_rows": len(trane_rows),
        "ok": len(trane_rows) > 0,
    }


def lint_bundle(site_id: str, building_id: str) -> dict:
    prefix = rule_id_prefix(site_id)
    ahu_eid = equipment_id(site_id, building_id, "rtu-01")
    specs = gl36_rule_specs(
        site_id=site_id,
        prefix=prefix,
        ahu_equipment_id=ahu_eid,
        fan_point_id="1100-analog-output-1",
        zone_avg_cols=[],
        column_map={},
    )
    enabled = [s for s in specs if s.get("enabled", True)]
    disabled = [s for s in specs if not s.get("enabled", True)]
    issues: list[str] = []
    for spec in specs:
        code = _read(spec["code_file"])
        is_script = (spec.get("mode") or "rule") == "script"
        lint = lint_python(code, require_arrow_rule=not is_script)
        if not lint["ok"]:
            issues.append(f"{spec['id']}: {lint['issues']}")
    return {
        "rule_count_total": len(specs),
        "rule_count_enabled": len(enabled),
        "rule_count_disabled": len(disabled),
        "enabled_ids": [s["id"] for s in enabled],
        "disabled_ids": [s["id"] for s in disabled],
        "lint_ok": not issues,
        "lint_issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Acme VAV/AHU FDD bundle")
    parser.add_argument("--site-id", default="acme")
    parser.add_argument("--building-id", default="vm-bbartling")
    parser.add_argument("--model", default=str(REPO / "edge_config/acme/vm-bbartling/model.json"))
    parser.add_argument("--profiles", default=str(REPO / "edge_config/acme/vm-bbartling/device_poll_profiles.csv"))
    args = parser.parse_args()

    report = {
        "model": audit_model(Path(args.model)),
        "poll_profiles": audit_poll_profiles(Path(args.profiles)),
        "rules": lint_bundle(args.site_id, args.building_id),
    }
    print(json.dumps(report, indent=2))
    ok = report["model"]["ok"] and report["poll_profiles"]["ok"] and report["rules"]["lint_ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
