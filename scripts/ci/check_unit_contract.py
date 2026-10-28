#!/usr/bin/env python3
"""T1284-1 — metric unit contract checks (#1284 W2a)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    GOLDENS,
    MANIFEST,
    METRIC_UNITS,
    REGISTRY,
    RENAME_MAP,
    TUNING,
    apply_tuning_catalog,
    collect_alias_map,
    derive_tuner_effect,
    infer_kind,
    inject_registry_kinds,
    load_json,
    normalize_alias,
    registry_param_blocks,
    sha256_file,
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_metric_units() -> None:
    if not METRIC_UNITS.is_file():
        fail(f"missing {METRIC_UNITS.relative_to(ROOT)}")
    body = load_json(METRIC_UNITS)
    if body.get("processing_abi_current") != "metric-c-v2":
        fail("metric_units.json processing_abi_current must be metric-c-v2")
    for q in body.get("quantities", []):
        if "pack_v1_unit" in q:
            fail(f"quantity {q.get('id')} still has pack_v1_unit")
    unsupported = {e["rule_id"] for e in body.get("unsupported_rules", []) if e.get("status") == "unsupported"}
    if "SV-RATE" not in unsupported:
        fail("SV-RATE must be listed unsupported in metric_units.json")
    try:
        collect_alias_map(body)
    except ValueError as exc:
        fail(str(exc))
    print("PASS metric_units.json structure")


def check_rename_map() -> None:
    metric = load_json(METRIC_UNITS)
    renames = load_json(RENAME_MAP).get("renames", {})
    if not isinstance(renames, dict) or not renames:
        fail("parameter_si_rename_map.json renames must be non-empty")
    for old, new in renames.items():
        if old == new:
            fail(f"rename map identity entry: {old}")
        if old.endswith("_f") and new != old[:-2]:
            fail(f"rename map must strip _f suffix: {old} -> {new}")
    path = metric.get("parameter_si_rename_map")
    if path != "sql/contract/parameter_si_rename_map.json":
        fail("metric_units.json must point at parameter_si_rename_map.json")
    print(f"PASS parameter_si_rename_map ({len(renames)} entries)")


def check_manifest_digest() -> None:
    if not MANIFEST.is_file():
        fail("missing sql/contract/manifest.json")
    manifest = load_json(MANIFEST)
    digest = sha256_file(METRIC_UNITS)
    if manifest.get("metric_units_sha256") != digest:
        fail(
            "manifest metric_units_sha256 mismatch "
            f"(manifest={manifest.get('metric_units_sha256')} file={digest})"
        )
    if manifest.get("processing_abi") != "metric-c-v2":
        fail("manifest processing_abi must be metric-c-v2")
    status = manifest.get("metric_storage_status")
    if status == "released":
        fail("metric_storage_status must not be released until W7")
    print("PASS manifest metric_units_sha256 and processing_abi")


def registry_param_kind(text: str, key: str, unit: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(rf"^      {re.escape(key)}:\s*$", line):
            continue
        saw_unit = False
        for j in range(i + 1, len(lines)):
            row = lines[j]
            if re.match(r"^      \w", row):
                break
            if not row.startswith("        "):
                break
            if re.match(rf"^        unit: {re.escape(unit)}\s*$", row):
                saw_unit = True
                continue
            if saw_unit:
                m = re.match(r"^        kind: (\S+)\s*$", row)
                if m:
                    return m.group(1)
        return None
    return None


def check_registry_kinds() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    missing = []
    for key, unit, _ in registry_param_blocks(text):
        kind = registry_param_kind(text, key, unit)
        if kind is None:
            missing.append(key)
            continue
        expected = infer_kind(key, unit)
        if kind != expected:
            fail(f"registry {key}: kind {kind} != expected {expected}")
    if missing:
        fail(f"registry parameters missing kind: {missing[:20]} (total {len(missing)})")
    print(f"PASS registry.yaml parameter kinds ({len(list(registry_param_blocks(text)))})")


def check_tuning_catalog() -> None:
    data = load_json(TUNING)
    expected = apply_tuning_catalog(json.loads(json.dumps(data)))
    for rule_a, rule_b in zip(data["rules"], expected["rules"], strict=True):
        rid = rule_a["rule_id"]
        pa = rule_a.get("parameters") or {}
        pb = rule_b.get("parameters") or {}
        for key in pa:
            if key not in pb:
                fail(f"{rid} parameter {key} missing from expected catalog")
            if pa[key].get("kind") != pb[key]["kind"]:
                fail(f"{rid}.{key} kind mismatch")
            if pa[key].get("effect") != pb[key]["effect"]:
                fail(f"{rid}.{key} effect must be {pb[key]['effect']}")
            derived = derive_tuner_effect(rid, pa[key].get("effect_in_sql"))
            if pa[key].get("effect") != derived:
                fail(f"{rid}.{key} effect must match derive_tuner_effect")
    print(f"PASS tuning_catalog kinds and tuner effects")


def check_goldens_roundtrip() -> None:
    """Rust fdd_core tests own vector math; here we verify golden file coverage."""
    if not GOLDENS.is_file():
        fail("missing unit_vectors.json")
    cases = load_json(GOLDENS)["cases"]
    required_kinds = {
        "absolute_temperature",
        "temperature_difference",
        "temperature_rate",
        "air_pressure",
        "hydronic_pressure",
        "volumetric_flow",
        "percent",
        "fraction",
    }
    seen = {c.get("kind") for c in cases}
    missing = required_kinds - seen
    if missing:
        fail(f"unit_vectors.json missing kinds: {sorted(missing)}")
    metric = load_json(METRIC_UNITS)
    aliases = collect_alias_map(metric)
    for alias in ("degf", "degc", "inwc", "cfm", "psi", "deltaf", "degfperh"):
        if alias not in aliases:
            fail(f"expected alias token {alias!r} in metric_units.json")
    print("PASS unit_vectors.json coverage")


def main() -> int:
    print("== check_unit_contract (T1284-1) ==")
    check_metric_units()
    check_rename_map()
    check_manifest_digest()
    check_registry_kinds()
    check_tuning_catalog()
    check_goldens_roundtrip()
    print("All unit contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
