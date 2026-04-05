#!/usr/bin/env python3
"""
Illustration only: how *different* semantic stacks can all produce the same kind of
artifact — a ``column_map`` dict for :class:`open_fdd.engine.runner.RuleRunner`.

Open-FDD does not ship Haystack, Google Digital Buildings (GDB/DBO), or ASHRAE 223P
clients here. In production you would query *your* graph or tag database and build
the dict. This script uses **static dicts** that mimic the *shape* of what each
integration might emit for **one** AHU supply-air temperature bound to column ``sat``.

Run:

    python examples/column_map_resolver_workshop/demo_multi_ontology_illustration.py
"""
from __future__ import annotations

from pathlib import Path

from open_fdd.engine.column_map_resolver import (
    FirstWinsCompositeResolver,
    ManifestColumnMapResolver,
    load_column_map_manifest,
)


def column_map_from_brick_convention() -> dict[str, str]:
    """Keys match Brick local class names (as in resolve_from_ttl output)."""
    return {"Supply_Air_Temperature_Sensor": "sat"}


def column_map_from_haystack_convention() -> dict[str, str]:
    """Example: keys are stable slugs you chose after resolving Haystack refs."""
    return {"discharge_air_temp_sensor": "sat"}


def column_map_from_dbo_convention() -> dict[str, str]:
    """Example: GDB-style type or entity id → column (your vocabulary)."""
    return {"SupplyAirTemperatureSensor": "sat"}


def column_map_from_223p_convention() -> dict[str, str]:
    """Example: scoped key after traversing equipment / connection (illustrative)."""
    return {"AHU-1/supply_air_temp": "sat"}


def main() -> None:
    root = Path(__file__).resolve().parent

    print("--- Static illustrations (same physical column 'sat') ---")
    for name, fn in [
        ("Brick-style keys", column_map_from_brick_convention),
        ("Haystack-derived slugs", column_map_from_haystack_convention),
        ("DBO / GDB-style", column_map_from_dbo_convention),
        ("223P-scoped label", column_map_from_223p_convention),
    ]:
        print(f"{name}: {fn()}")

    print("\n--- Files in this folder (YAML manifests) ---")
    for path in sorted(root.glob("manifest_*.yaml")):
        print(path.name, "->", load_column_map_manifest(path))

    print("\n--- FirstWinsCompositeResolver (Brick TTL + manifest gap-fill) ---")
    print(
        "Use BrickTtlColumnMapResolver() first, then ManifestColumnMapResolver(extra.yaml), "
        "so TTL defines most points and a small manifest adds keys TTL does not cover."
    )
    # Optional: if repo has a tiny TTL, could demo composite; keep script dependency-free.
    _ = FirstWinsCompositeResolver(ManifestColumnMapResolver(root / "manifest_minimal.yaml"))
    print("Composite constructed OK (see tests for Brick + manifest example).")


if __name__ == "__main__":
    main()
