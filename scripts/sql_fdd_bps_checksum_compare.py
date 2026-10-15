#!/usr/bin/env python3
"""C2 Soft-OPEN: checksum OSS tip FDD SQL (77) vs optional BPS vendor warehouse.

Canonical OSS pack: ``sql/fdd/postgres/rules`` + ``sql/fdd/registry.yaml``.
Do **not** compare legacy ``sql_rules/`` (DataFusion-era surface) — equations live
under ``sql/fdd``.

Modes:
  1) Self-pin (CI / no vendor mount): verify 77 rule files + registry match
     ``sql/contract/manifest.json`` entries (fail on equation / catalog drift).
  2) Vendor compare: ``--bps-root`` or ``OPENFDD_BPS_WAREHOUSE_ROOT`` points at a
     public/synthetic warehouse tree whose ``sql/postgres/rules`` + ``sql/registry.yaml``
     must be byte-identical to OSS tip.

Public / synthetic material only. Soft-OPEN ≠ FQ. No Parquet restore.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OSS_RULES = ROOT / "sql" / "fdd" / "postgres" / "rules"
OSS_REGISTRY = ROOT / "sql" / "fdd" / "registry.yaml"
MANIFEST = ROOT / "sql" / "contract" / "manifest.json"
EXPECTED_RULE_COUNT = 77


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rule_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"missing rules directory: {directory}")
    files = {p.name: p for p in sorted(directory.glob("*.sql"))}
    return files


def count_registry_rules(registry: Path) -> int:
    text = registry.read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("- rule_id:"))


def self_pin_against_manifest() -> list[str]:
    """Fail if OSS tip sql/fdd rules/registry drift from contract ledger."""
    errors: list[str] = []
    if not MANIFEST.is_file():
        return [f"missing contract manifest: {MANIFEST}"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_path = {e["path"]: e for e in manifest.get("files") or []}

    oss = rule_files(OSS_RULES)
    if len(oss) != EXPECTED_RULE_COUNT:
        errors.append(f"OSS rule count={len(oss)} want {EXPECTED_RULE_COUNT}")

    if not OSS_REGISTRY.is_file():
        errors.append(f"missing OSS registry: {OSS_REGISTRY}")
    else:
        n = count_registry_rules(OSS_REGISTRY)
        if n != EXPECTED_RULE_COUNT:
            errors.append(f"OSS registry rule_id count={n} want {EXPECTED_RULE_COUNT}")
        rel = "sql/fdd/registry.yaml"
        entry = by_path.get(rel)
        if entry is None:
            errors.append(f"contract manifest missing {rel}")
        else:
            dig = sha256_file(OSS_REGISTRY)
            if dig != entry.get("sha256") or OSS_REGISTRY.stat().st_size != int(
                entry.get("bytes") or -1
            ):
                errors.append(
                    f"{rel}: disk sha/bytes={dig[:16]}…/{OSS_REGISTRY.stat().st_size} "
                    f"manifest={str(entry.get('sha256', ''))[:16]}…/{entry.get('bytes')}"
                )

    for name, path in oss.items():
        rel = f"sql/fdd/postgres/rules/{name}"
        entry = by_path.get(rel)
        if entry is None:
            errors.append(f"contract manifest missing {rel}")
            continue
        dig = sha256_file(path)
        if dig != entry.get("sha256") or path.stat().st_size != int(entry.get("bytes") or -1):
            errors.append(
                f"{rel}: disk sha/bytes={dig[:16]}…/{path.stat().st_size} "
                f"manifest={str(entry.get('sha256', ''))[:16]}…/{entry.get('bytes')}"
            )
    return errors


def vendor_compare(bps_root: Path) -> list[str]:
    """Byte-compare OSS tip sql/fdd ↔ BPS warehouse sql/postgres (77 + registry)."""
    errors: list[str] = []
    bps_rules = bps_root / "sql" / "postgres" / "rules"
    bps_registry = bps_root / "sql" / "registry.yaml"
    try:
        bps = rule_files(bps_rules)
    except FileNotFoundError as exc:
        return [str(exc)]

    oss = rule_files(OSS_RULES)
    if len(bps) != EXPECTED_RULE_COUNT:
        errors.append(f"BPS rule count={len(bps)} want {EXPECTED_RULE_COUNT}")
    if len(oss) != EXPECTED_RULE_COUNT:
        errors.append(f"OSS rule count={len(oss)} want {EXPECTED_RULE_COUNT}")

    only_bps = sorted(set(bps) - set(oss))
    only_oss = sorted(set(oss) - set(bps))
    if only_bps:
        errors.append(f"BPS-only rule files ({len(only_bps)}): {only_bps[:5]}")
    if only_oss:
        errors.append(f"OSS-only rule files ({len(only_oss)}): {only_oss[:5]}")

    drifted = []
    for name in sorted(set(bps) & set(oss)):
        if sha256_file(bps[name]) != sha256_file(oss[name]):
            drifted.append(name)
    if drifted:
        errors.append(
            f"equation drift ({len(drifted)}/{len(set(bps) & set(oss))} files): "
            f"{drifted[:8]}{'…' if len(drifted) > 8 else ''}"
        )

    if not bps_registry.is_file():
        errors.append(f"missing BPS registry: {bps_registry}")
    elif not OSS_REGISTRY.is_file():
        errors.append(f"missing OSS registry: {OSS_REGISTRY}")
    elif sha256_file(bps_registry) != sha256_file(OSS_REGISTRY):
        errors.append(
            "registry.yaml drift between BPS warehouse and OSS sql/fdd "
            f"(bps={sha256_file(bps_registry)[:16]}… oss={sha256_file(OSS_REGISTRY)[:16]}…)"
        )
    else:
        n = count_registry_rules(OSS_REGISTRY)
        if n != EXPECTED_RULE_COUNT:
            errors.append(f"registry rule_id count={n} want {EXPECTED_RULE_COUNT}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="C2 Soft-OPEN FDD SQL checksum compare (77 rules; Soft-OPEN ≠ FQ)"
    )
    parser.add_argument(
        "--bps-root",
        type=Path,
        default=None,
        help="Optional BPS/vendor openfdd-warehouse root (or set OPENFDD_BPS_WAREHOUSE_ROOT)",
    )
    parser.add_argument(
        "--skip-self-pin",
        action="store_true",
        help="Skip OSS tip vs sql/contract/manifest self-pin (vendor-only)",
    )
    args = parser.parse_args(argv)

    print("== C2 Soft-OPEN FDD SQL checksum compare (≠ FQ) ==")
    print(f"OSS rules: {OSS_RULES}")
    fail = 0

    if not args.skip_self_pin:
        pin_errs = self_pin_against_manifest()
        if pin_errs:
            print("FAIL: OSS tip self-pin vs contract manifest:")
            for row in pin_errs:
                print(f"  - {row}")
            fail = 1
        else:
            print(
                f"OK: OSS tip self-pin ({EXPECTED_RULE_COUNT} rules + registry match contract)"
            )

    bps_root = args.bps_root
    if bps_root is None:
        env = os.environ.get("OPENFDD_BPS_WAREHOUSE_ROOT", "").strip()
        if env:
            bps_root = Path(env)

    if bps_root is None:
        print(
            "OK: vendor compare SKIPPED (set --bps-root or OPENFDD_BPS_WAREHOUSE_ROOT for "
            "BPS↔OSS byte compare)"
        )
    else:
        print(f"BPS root: {bps_root}")
        vend_errs = vendor_compare(bps_root)
        if vend_errs:
            print("FAIL: BPS↔OSS equation/catalog drift:")
            for row in vend_errs:
                print(f"  - {row}")
            fail = 1
        else:
            print(
                f"OK: BPS↔OSS byte-identical ({EXPECTED_RULE_COUNT} postgres rules + registry)"
            )

    if fail:
        print("C2 checksum compare FAILED (equation drift — Soft-OPEN ≠ FQ)")
        return 1
    print("C2 checksum compare PASS (smoke pin — Soft-OPEN ≠ FQ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
