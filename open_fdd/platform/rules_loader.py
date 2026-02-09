"""
Rules loader with hot-reload: check YAML mtime/hash, reload when changed.

Used by FDD loop to pick up analyst tuning without restart.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from open_fdd.engine.runner import load_rules_from_dir


def _rules_dir_hash(rules_dir: Path) -> str:
    """Hash of all YAML file mtimes + contents for change detection."""
    if not rules_dir.exists():
        return ""
    paths = sorted(rules_dir.glob("*.yaml"))
    if not paths:
        return ""
    hasher = hashlib.sha256()
    for p in paths:
        st = p.stat()
        hasher.update(f"{p.name}:{st.st_mtime}:{st.st_size}".encode())
        hasher.update(p.read_bytes())
    return hasher.hexdigest()


class HotReloadRules:
    """Cache rules and reload when YAML dir changes."""

    def __init__(self, rules_dir: Path, datalake_override: Optional[Path] = None):
        self.rules_dir = Path(rules_dir)
        self.datalake_override = Path(datalake_override) if datalake_override else None
        self._hash = ""
        self._rules: list = []
        self._column_map: dict = {}
        self._equipment_types: list = []

    def _effective_dir(self) -> Path:
        if self.datalake_override and self.datalake_override.exists():
            return self.datalake_override
        return self.rules_dir

    def _check_reload(self) -> None:
        eff = self._effective_dir()
        h = _rules_dir_hash(eff)
        if h != self._hash:
            self._hash = h
            self._rules = load_rules_from_dir(eff)
            try:
                from open_fdd.engine.brick_resolver import (
                    resolve_from_ttl,
                    get_equipment_types_from_ttl,
                )

                ttl = eff.parent / "data" / "brick_model.ttl"
                if ttl.exists():
                    self._column_map = resolve_from_ttl(str(ttl))
                    self._equipment_types = get_equipment_types_from_ttl(str(ttl))
                else:
                    self._column_map = {}
                    self._equipment_types = []
            except Exception:
                self._column_map = {}
                self._equipment_types = []

    @property
    def rules(self) -> list:
        self._check_reload()
        return self._rules

    @property
    def column_map(self) -> dict:
        self._check_reload()
        return self._column_map

    @property
    def equipment_types(self) -> list:
        self._check_reload()
        return self._equipment_types
