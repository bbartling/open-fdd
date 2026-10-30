#!/usr/bin/env python3
"""T1284-1 — metric unit contract checks (#1284 W2a)."""

from __future__ import annotations

import json
import sys
import re
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
    assert_ip_unit_declared,
    assert_unit_matches_kind,
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
    metric = load_json(METRIC_UNITS)
    text = REGISTRY.read_text(encoding="utf-8")
    missing = []
    for rule_id, key, unit, _ in registry_param_blocks(text):
        kind = registry_param_kind(text, rule_id, key, unit)
        if kind is None:
            missing.append(f"{rule_id}.{key}")
            continue
        try:
            assert_unit_matches_kind(metric, f"registry {rule_id}.{key}", kind, unit)
        except ValueError as exc:
            fail(str(exc))
    import yaml

    for rule in (yaml.safe_load(text) or {}).get("rules") or []:
        rid = str(rule.get("rule_id") or "")
        for key, param in (rule.get("parameters") or {}).items():
            if not isinstance(param, dict) or not param.get("kind"):
                continue
            try:
                assert_ip_unit_declared(metric, f"registry {rid}.{key}", str(param["kind"]), param)
            except ValueError as exc:
                fail(str(exc))
    if missing:
        fail(f"registry parameters missing kind: {missing[:20]} (total {len(missing)})")
    print(f"PASS registry.yaml parameter kinds ({len(list(registry_param_blocks(text)))})")


def check_tuning_catalog() -> None:
    data = load_json(TUNING)
    try:
        expected = apply_tuning_catalog(json.loads(json.dumps(data)))
    except ValueError as exc:
        fail(str(exc))
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


def check_pa_per_in_wc_product_sites() -> None:
    """W6-pre: every in.w.c.→Pa site must match metric_units.json PA_PER_IN_WC."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    metric = load_json(METRIC_UNITS)
    contract = float((metric.get("constants") or {})["PA_PER_IN_WC"])
    if abs(contract - 248.84) > 1e-9:
        fail(f"unexpected contract PA_PER_IN_WC literal: {contract}")

    from open_fdd.units.convert import PA_PER_IN_WC as py_convert

    if abs(py_convert - contract) > 1e-9:
        fail(f"open_fdd.units.convert.PA_PER_IN_WC={py_convert} != contract {contract}")

    import importlib.util

    profiles_path = ROOT / "open_fdd" / "rules" / "sensor_rate_profiles.py"
    spec = importlib.util.spec_from_file_location(
        "_ofdd_sensor_rate_profiles_contract",
        profiles_path,
    )
    if spec is None or spec.loader is None:
        fail("could not load sensor_rate_profiles.py")
    profiles = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = profiles
    spec.loader.exec_module(profiles)
    if abs(profiles.IN_WC_TO_PA - contract) > 1e-9:
        fail(f"sensor_rate_profiles.IN_WC_TO_PA={profiles.IN_WC_TO_PA} != contract")

    quality_path = ROOT / "open_fdd" / "quality.py"
    quality_text = quality_path.read_text(encoding="utf-8")
    if "249.088" in quality_text:
        fail("quality.py still references the 4 °C in.w.c. factor literal")
    if "PA_PER_IN_WC" not in quality_text:
        fail("quality.py must import PA_PER_IN_WC for in.w.c. bound scaling")

    sweep_path = ROOT / "crates" / "fdd_core" / "src" / "sensor_sweep.rs"
    sweep_text = sweep_path.read_text(encoding="utf-8")
    if "249.088" in sweep_text:
        fail("sensor_sweep.rs still references the 4 °C in.w.c. factor literal")
    if "const PA_PER_IN_WC: f64 = 248.84" not in sweep_text:
        fail("sensor_sweep.rs must define PA_PER_IN_WC = 248.84")

    ts_path = ROOT / "frontend" / "web" / "src" / "api" / "roleUnits.ts"
    text = ts_path.read_text(encoding="utf-8")
    match = re.search(r"export const INWC_TO_PA = ([0-9.]+);", text)
    if not match:
        fail("roleUnits.ts missing export const INWC_TO_PA")
    ts_val = float(match.group(1))
    if abs(ts_val - contract) > 1e-9:
        fail(f"roleUnits INWC_TO_PA={ts_val} != contract {contract}")

    print(f"PASS PA_PER_IN_WC contract parity ({contract}) across Python + SPA sites")


def check_metadata_only_diff() -> None:
    try:
        assert_metadata_only_registry_diff()
        assert_metadata_only_tuning_diff()
    except (AssertionError, RuntimeError) as exc:
        fail(str(exc))
    print(
        "PASS registry.yaml and tuning_catalog.json differ from merge-base with the "
        "default branch only by kind/effect, declared-kind SI cutover, additive "
        "equipment_kinds, and SQL-justified optional_roles additions"
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
    check_pa_per_in_wc_product_sites()
    check_metadata_only_diff()
    print("All unit contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
