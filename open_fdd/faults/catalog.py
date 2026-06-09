"""Load Grade-A fault definitions from YAML catalog files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .schema import FaultDefinition

CATALOG_VERSION = 1
_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
_catalog_cache: dict[str, FaultDefinition] | None = None
_alias_cache: dict[str, str] | None = None


def _yaml_files() -> list[Path]:
    if not _CATALOG_DIR.is_dir():
        return []
    return sorted(_CATALOG_DIR.glob("*.yaml"))


def load_catalog() -> dict[str, FaultDefinition]:
    """All faults keyed by ``code``."""
    global _catalog_cache, _alias_cache
    if _catalog_cache is not None:
        return _catalog_cache

    faults: dict[str, FaultDefinition] = {}
    alias_index: dict[str, str] = {}

    for path in _yaml_files():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        for item in raw.get("faults") or []:
            if not isinstance(item, dict):
                continue
            fault = FaultDefinition.from_dict(item)
            errors = fault.validate()
            if errors:
                raise ValueError(f"{path.name} fault {fault.code}: {', '.join(errors)}")
            faults[fault.code] = fault
            for alias in fault.legacy_aliases:
                alias_index[str(alias).strip().upper()] = fault.code

    _catalog_cache = faults
    _alias_cache = alias_index
    return faults


def catalog_version() -> int:
    return CATALOG_VERSION


def list_faults(*, family: str | None = None) -> list[FaultDefinition]:
    catalog = load_catalog()
    items = list(catalog.values())
    if family:
        fam = family.strip().upper()
        items = [f for f in items if f.family == fam]
    return sorted(items, key=lambda f: f.code)


def list_families() -> list[str]:
    return sorted({f.family for f in load_catalog().values()})


def get_fault(code: str) -> FaultDefinition | None:
    key = str(code or "").strip().upper()
    catalog = load_catalog()
    if key in catalog:
        return catalog[key]
    load_catalog()
    resolved = (_alias_cache or {}).get(key)
    if resolved:
        return catalog.get(resolved)
    return None


def legacy_alias(letter_code: str) -> str | None:
    """Map v2 letter code (e.g. AHU-E) to Grade-A code if aliased."""
    fault = get_fault(letter_code)
    return fault.code if fault else None


def catalog_export() -> dict[str, Any]:
    """JSON-serializable catalog for API / portfolio."""
    faults = load_catalog()
    return {
        "version": catalog_version(),
        "families": list_families(),
        "faults": [f.to_dict() for f in sorted(faults.values(), key=lambda x: x.code)],
    }
