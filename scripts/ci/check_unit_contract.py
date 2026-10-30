#!/usr/bin/env python3
"""T1284-1 — metric unit contract checks (#1284 W2a)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from unit_contract_lib import (  # noqa: E402
    ALIAS_GOLDENS,
    GOLDENS,
    MANIFEST,
    METRIC_UNITS,
    REGISTRY,
    RENAME_MAP,
    TUNING,
    apply_tuning_catalog,
    assert_metadata_only_registry_diff,
    assert_metadata_only_tuning_diff,
    build_conversion_index,
    collect_alias_map,
    convert_to_canonical,
    derive_tuner_effect,
    infer_kind,
    load_json,
    normalize_alias,
    registry_param_blocks,
    registry_param_kind,
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
        build_conversion_index(body)
    except ValueError as exc:
        fail(str(exc))
    print("PASS metric_units.json structure")


def check_every_alias_converts() -> None:
    metric = load_json(METRIC_UNITS)
    by_token = build_conversion_index(metric)
    for q in metric.get("quantities", []):
        if q["id"] == "occupancy_mode":
            continue
        for alias in q.get("aliases") or []:
            tok = normalize_alias(alias)
            if tok not in by_token:
                fail(f"alias {alias!r} (token {tok}) has no conversion row")
            try:
                convert_to_canonical(metric, q["id"], 1.0, alias)
            except ValueError as exc:
                fail(f"convert failed for {q['id']} alias {alias!r}: {exc}")
    print(f"PASS all quantity aliases convert ({len(by_token)} tokens)")


def check_alias_normalize_goldens() -> None:
    if not ALIAS_GOLDENS.is_file():
        fail("missing alias_normalize_tokens.json")
    for case in load_json(ALIAS_GOLDENS)["cases"]:
        got = normalize_alias(case["input"])
        if got != case["token"]:
            fail(f"normalize_alias({case['input']!r}) = {got!r}, want {case['token']!r}")
    print("PASS alias_normalize_tokens.json (Python)")


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


def check_registry_kinds() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    missing = []
    for rule_id, key, unit, _ in registry_param_blocks(text):
        kind = registry_param_kind(text, rule_id, key, unit)
        if kind is None:
            missing.append(f"{rule_id}.{key}")
            continue
        expected = infer_kind(key, unit)
        if kind != expected:
            fail(f"registry {rule_id}.{key}: kind {kind} != expected {expected}")
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
    print("PASS tuning_catalog kinds and tuner effects")


def check_goldens_roundtrip() -> None:
    if not GOLDENS.is_file():
        fail("missing unit_vectors.json")
    metric = load_json(METRIC_UNITS)
    for case in load_json(GOLDENS)["cases"]:
        qty = case.get("quantity")
        src = case.get("source_unit")
        inp = case.get("input")
        want = case.get("metric")
        if qty is None:
            continue
        tol = case.get("tol", 1e-9)
        got = convert_to_canonical(metric, qty, float(inp), str(src))
        if abs(got - float(want)) > float(tol):
            fail(f"{case['id']}: got {got} want {want}")
    print("PASS unit_vectors.json conversion goldens (Python)")


def check_metadata_only_diff() -> None:
    try:
        assert_metadata_only_registry_diff()
        assert_metadata_only_tuning_diff()
    except (AssertionError, RuntimeError) as exc:
        fail(str(exc))
    print(
        "PASS registry.yaml and tuning_catalog.json differ from merge-base with the "
        "default branch only by kind/effect and SQL-justified optional_roles additions"
    )


def main() -> int:
    print("== check_unit_contract (T1284-1) ==")
    check_metric_units()
    check_every_alias_converts()
    check_alias_normalize_goldens()
    check_rename_map()
    check_manifest_digest()
    check_registry_kinds()
    check_tuning_catalog()
    check_goldens_roundtrip()
    check_metadata_only_diff()
    print("All unit contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
