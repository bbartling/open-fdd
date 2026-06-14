"""Durable store for saved Rule Lab Python rules (``data/rules_store.json``).

Rules use the Arrow backend (``apply_faults_arrow``) on PyArrow tables.
``backend: arrow`` is detected from source; legacy ``evaluate()`` is not supported.
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



def _short_description(entry: dict[str, Any]) -> str:
    desc = str(entry.get("short_description") or entry.get("description") or "").strip()
    if desc:
        return desc[:240]
    name = str(entry.get("name") or "").strip()
    return name[:240] if name else "Fault detected"


_LOCK = threading.RLock()

VALID_MODES = frozenset({"rule", "script"})
VALID_SEVERITIES = frozenset({"info", "warning", "critical"})


def _normalize_bindings(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {
            "point_ids": [],
            "direct_point_ids": [],
            "equipment_ids": [],
            "brick_types": [],
        }
    point_ids = [str(x) for x in raw.get("point_ids", []) if str(x).strip()]
    direct = raw.get("direct_point_ids")
    if direct is None:
        direct_point_ids = list(point_ids)
    else:
        direct_point_ids = [str(x) for x in direct if str(x).strip()]
    return {
        "point_ids": point_ids,
        "direct_point_ids": direct_point_ids,
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
        out: list[dict[str, Any]] = []
        for rule in self.load().get("rules", []):
            if not isinstance(rule, dict):
                continue
            out.append(self._hydrate_rule_code(dict(rule)))
        return out

    def _hydrate_rule_code(self, rule: dict[str, Any]) -> dict[str, Any]:
        path = str(rule.get("source_path") or "")
        if path:
            disk = read_source(path)
            if disk.strip():
                rule = dict(rule)
                rule["code"] = disk
        return rule

    def get(self, rule_id: str) -> dict[str, Any] | None:
        for rule in self.list_rules():
            if str(rule.get("id")) == str(rule_id):
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

    def prune_bindings(
        self,
        *,
        point_ids: list[str] | None = None,
        equipment_ids: list[str] | None = None,
    ) -> int:
        """Remove stale point/equipment ids from every rule binding. Returns rules updated."""
        pset = {str(x).strip() for x in (point_ids or []) if str(x).strip()}
        eset = {str(x).strip() for x in (equipment_ids or []) if str(x).strip()}
        if not pset and not eset:
            return 0
        changed = 0
        with _LOCK:
            doc = self.load()
            rules = [r for r in doc.get("rules", []) if isinstance(r, dict)]
            for rule in rules:
                b = _normalize_bindings(rule.get("bindings"))
                before = (
                    tuple(b["point_ids"]),
                    tuple(b["direct_point_ids"]),
                    tuple(b["equipment_ids"]),
                )
                if pset:
                    b["point_ids"] = [x for x in b["point_ids"] if x not in pset]
                    b["direct_point_ids"] = [x for x in b["direct_point_ids"] if x not in pset]
                if eset:
                    b["equipment_ids"] = [x for x in b["equipment_ids"] if x not in eset]
                after = (
                    tuple(b["point_ids"]),
                    tuple(b["direct_point_ids"]),
                    tuple(b["equipment_ids"]),
                )
                if before != after:
                    rule["bindings"] = b
                    rule["updated_at"] = _now()
                    changed += 1
            if changed:
                doc["rules"] = rules
                self._save(doc)
        return changed

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


def _lint_rule_code(code: str, *, mode: str, backend: str = "", sql: str = "", fault_column: str = "fault") -> None:
    """Reject pandas/legacy patterns before persisting a rule."""
    from open_fdd.arrow_runtime.datafusion_backend import lint_datafusion_sql_rule
    from open_fdd.arrow_runtime.rules import detect_rule_backend

    from . import playground

    if backend == "datafusion_sql" or str(sql or "").strip():
        lint = lint_datafusion_sql_rule(sql, fault_column=fault_column or "fault")
        if lint.get("ok"):
            return
        msgs = [
            str(i.get("message") or "lint failed")
            for i in lint.get("issues", [])
            if i.get("severity") == "error"
        ]
        raise ValueError("SQL lint failed:\n" + "\n".join(msgs) if msgs else "SQL lint failed")
    if mode == "script":
        lint = playground.lint_python(
            code,
            require_arrow_rule=False,
            require_evaluate=False,
            strict_imports=True,
        )
    elif detect_rule_backend(code, {"mode": mode}) == "arrow":
        lint = playground.lint_arrow_python(code)
    else:
        lint = playground.lint_python(code, strict_imports=True)
    if lint.get("ok"):
        return
    msgs = [
        str(i.get("message") or "lint failed")
        for i in lint.get("issues", [])
        if i.get("severity") == "error"
    ]
    raise ValueError("rule lint failed:\n" + "\n".join(msgs) if msgs else "rule lint failed")


def normalize_rule(entry: dict[str, Any], *, saved_by: str = "operator") -> dict[str, Any]:
    mode = str(entry.get("mode") or "rule")
    if mode not in VALID_MODES:
        mode = "rule"
    severity = str(entry.get("severity") or "warning")
    if severity not in VALID_SEVERITIES:
        severity = "warning"
    code = str(entry.get("code") or "")
    sql = str(entry.get("sql") or "").strip()
    fault_column = str(entry.get("fault_column") or "fault").strip() or "fault"
    path = str(entry.get("source_path") or "")
    resolved_backend = backend
    if backend == "datafusion_sql" or sql:
        if not sql:
            raise ValueError("datafusion_sql rules require sql field")
        _lint_rule_code(code, mode=mode, backend="datafusion_sql", sql=sql, fault_column=fault_column)
        if not code.strip():
            code = "# DataFusion SQL rule — see sql field"
        resolved_backend = "datafusion_sql"
    else:
        if path:
            disk = read_source(path)
            if disk.strip():
                code = disk
        if not code.strip():
            raise ValueError("rule code is required")
        _lint_rule_code(code, mode=mode)
    config = entry.get("config")
    if not isinstance(config, dict):
        config = {}
    column_map = entry.get("column_map")
    if not isinstance(column_map, dict):
        column_map = {}
    applies_to = entry.get("applies_to")
    if not isinstance(applies_to, dict):
        applies_to = {}
    if resolved_backend not in {"arrow", "legacy_row", "datafusion_sql"}:
        try:
            from open_fdd.arrow_runtime.rules import detect_rule_backend

            resolved_backend = detect_rule_backend(code, {"mode": mode, "sql": sql, "backend": resolved_backend})
            if resolved_backend == "script":
                resolved_backend = ""
        except Exception:
            resolved_backend = ""
    out = {
        "id": str(entry.get("id") or uuid4()),
        "name": str(entry.get("name") or "Untitled rule")[:200],
        "short_description": _short_description(entry),
        "description": str(entry.get("description") or "")[:1000],
        "mode": mode,
        "backend": resolved_backend,
        "code": code,
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
    if resolved_backend == "datafusion_sql":
        out["sql"] = sql
        out["fault_column"] = fault_column
    return out
