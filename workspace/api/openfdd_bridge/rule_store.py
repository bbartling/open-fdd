"""Durable store for saved Rule Lab Python rules (``data/rules_store.json``).

A saved rule is a Python ``evaluate()`` rule or a DataFrame script that was
validated in the browser Rule Lab and persisted so the scheduled FDD runner can
apply it across every BRICK-modeled site. This is distinct from the engine YAML
rules under ``data/rules/`` (which still run via :mod:`open_fdd.engine`).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .paths import data_dir
from .rule_source import read_source, write_source

_LOCK = threading.RLock()

VALID_MODES = frozenset({"rule", "script"})
VALID_SEVERITIES = frozenset({"info", "warning", "critical"})


def _normalize_bindings(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {"point_ids": [], "equipment_ids": [], "brick_types": []}
    return {
        "point_ids": [str(x) for x in raw.get("point_ids", []) if str(x).strip()],
        "equipment_ids": [str(x) for x in raw.get("equipment_ids", []) if str(x).strip()],
        "brick_types": [str(x) for x in raw.get("brick_types", []) if str(x).strip()],
    }


def rules_store_path() -> Path:
    return data_dir() / "rules_store.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RuleStore:
    path: Path = field(default_factory=rules_store_path)

    def _default(self) -> dict[str, Any]:
        return {"version": 1, "rules": []}

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._default()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._default()
        if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
            return self._default()
        return raw

    def list_rules(self) -> list[dict[str, Any]]:
        return list(self.load().get("rules", []))

    def get(self, rule_id: str) -> dict[str, Any] | None:
        for rule in self.list_rules():
            if str(rule.get("id")) == str(rule_id):
                path = str(rule.get("source_path") or "")
                if path:
                    disk = read_source(path)
                    if disk.strip():
                        rule = dict(rule)
                        rule["code"] = disk
                return rule
        return None

    def _save(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(doc, indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, mode="w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def upsert(self, entry: dict[str, Any], *, saved_by: str = "operator") -> dict[str, Any]:
        normalized = normalize_rule(entry, saved_by=saved_by)
        source_path = write_source(
            rule_id=normalized["id"],
            name=normalized["name"],
            code=normalized["code"],
            existing_path=normalized.get("source_path") or None,
        )
        normalized["source_path"] = source_path
        with _LOCK:
            doc = self.load()
            rules = [r for r in doc.get("rules", []) if isinstance(r, dict)]
            existing_idx = next(
                (i for i, r in enumerate(rules) if str(r.get("id")) == normalized["id"]),
                None,
            )
            if existing_idx is None:
                rules.append(normalized)
            else:
                normalized["created_at"] = rules[existing_idx].get("created_at") or normalized["created_at"]
                rules[existing_idx] = normalized
            doc["rules"] = rules
            self._save(doc)
        return normalized

    def delete(self, rule_id: str) -> bool:
        with _LOCK:
            doc = self.load()
            rules = [r for r in doc.get("rules", []) if isinstance(r, dict)]
            kept = [r for r in rules if str(r.get("id")) != str(rule_id)]
            if len(kept) == len(rules):
                return False
            doc["rules"] = kept
            self._save(doc)
        return True


def normalize_rule(entry: dict[str, Any], *, saved_by: str = "operator") -> dict[str, Any]:
    mode = str(entry.get("mode") or "rule")
    if mode not in VALID_MODES:
        mode = "rule"
    severity = str(entry.get("severity") or "warning")
    if severity not in VALID_SEVERITIES:
        severity = "warning"
    code = str(entry.get("code") or "")
    if not code.strip():
        raise ValueError("rule code is required")
    config = entry.get("config")
    if not isinstance(config, dict):
        config = {}
    column_map = entry.get("column_map")
    if not isinstance(column_map, dict):
        column_map = {}
    applies_to = entry.get("applies_to")
    if not isinstance(applies_to, dict):
        applies_to = {}
    return {
        "id": str(entry.get("id") or uuid4()),
        "name": str(entry.get("name") or "Untitled rule")[:200],
        "description": str(entry.get("description") or "")[:1000],
        "mode": mode,
        "code": code,
        "fault_code": str(entry.get("fault_code") or "").strip().upper()[:32],
        "config": config,
        "column_map": column_map,
        "applies_to": {
            "equipment_type": str(applies_to.get("equipment_type") or "").strip(),
            "brick_type": str(applies_to.get("brick_type") or "").strip(),
            "site_ids": [str(s) for s in applies_to.get("site_ids", []) if str(s).strip()],
        },
        "bindings": _normalize_bindings(entry.get("bindings")),
        "source_path": str(entry.get("source_path") or "").strip(),
        "severity": severity,
        "enabled": bool(entry.get("enabled", True)),
        "saved_by": saved_by,
        "created_at": str(entry.get("created_at") or _now()),
        "updated_at": _now(),
    }
