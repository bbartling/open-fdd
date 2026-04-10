"""
Pluggable resolution of rule input keys → DataFrame column names (column_map).

The full **AFDD stack** builds Brick TTL maps via ``BrickTtlColumnMapResolver`` in
**``afdd_stack/openfdd_stack``** (``openfdd_stack.platform.brick_ttl_resolver``), not in the ``open-fdd``
wheel. Integrators may pass any object satisfying :class:`ColumnMapResolver` into ``run_fdd_loop``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Protocol, Sequence, Union, runtime_checkable

import yaml


@runtime_checkable
class ColumnMapResolver(Protocol):
    """Builds the column_map passed to :meth:`open_fdd.engine.runner.RuleRunner.run`."""

    def build_column_map(self, *, ttl_path: Path) -> Dict[str, str]:
        """
        :param ttl_path: Resolved Brick TTL file path (may not exist — return {}).
        :return: Mapping from Brick class / rule_input keys to DataFrame column names.
        """


def _normalize_manifest_mapping(raw: object) -> Dict[str, str]:
    """Accept ``{"column_map": {...}}`` or a flat str→str mapping."""
    if not isinstance(raw, dict):
        return {}
    if "column_map" in raw and isinstance(raw["column_map"], dict):
        raw = raw["column_map"]
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if k == "column_map":
            continue
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def load_column_map_manifest(path: Union[str, Path]) -> Dict[str, str]:
    """
    Load a JSON or YAML manifest of logical key → DataFrame column name.

    Supported shapes:

    - Flat: ``{"Supply_Air_Temperature_Sensor": "sat", "oat": "outside_air_temp"}``
    - Wrapped: ``{"column_map": {...}, "description": "..."}``

    Uses ``yaml.safe_load`` for ``.yaml`` / ``.yml`` and ``json.load`` for ``.json``.
    """
    p = Path(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = yaml.safe_load(text)
    return _normalize_manifest_mapping(data)


class ManifestColumnMapResolver:
    """
    Workshop / engine-only helper: ``column_map`` from a JSON or YAML file on disk.

    ``build_column_map`` ignores ``ttl_path``; the manifest path is fixed at construction.
    Use :class:`FirstWinsCompositeResolver` to merge several manifest-style sources (first wins per key).
    """

    def __init__(self, manifest_path: Union[str, Path]) -> None:
        self._manifest_path = Path(manifest_path)

    def build_column_map(self, *, ttl_path: Path) -> Dict[str, str]:
        _ = ttl_path
        return load_column_map_manifest(self._manifest_path)


class FirstWinsCompositeResolver:
    """
    Run several resolvers in order; each key is taken from the **first** resolver that
    defines it (ontology-style priority without config import strings).

    Example: ``FirstWinsCompositeResolver(ManifestColumnMapResolver("base.yaml"), ManifestColumnMapResolver("extra.yaml"))``
    — first file wins for shared keys; second adds only **missing** keys.
    """

    def __init__(self, *resolvers: ColumnMapResolver) -> None:
        if not resolvers:
            raise ValueError("FirstWinsCompositeResolver requires at least one resolver")
        self._resolvers: Sequence[ColumnMapResolver] = resolvers

    def build_column_map(self, *, ttl_path: Path) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for resolver in self._resolvers:
            part = resolver.build_column_map(ttl_path=ttl_path)
            for k, v in part.items():
                if k not in out:
                    out[k] = v
        return out
