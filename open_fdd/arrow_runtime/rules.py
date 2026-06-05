"""Rule backend detection and legacy migration helpers."""

from __future__ import annotations

import ast
import os
import re
from typing import Any


def _has_function(code: str, name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return name in code
    return any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree))


def detect_rule_backend(code: str, rule: dict[str, Any] | None = None) -> str:
    """Return ``arrow``, ``legacy_row``, or ``script``."""
    rule = rule or {}
    if rule.get("mode") == "script":
        return "script"
    explicit = str(rule.get("backend") or "").strip()
    if explicit in {"arrow", "legacy_row"}:
        return explicit
    if _has_function(code, "apply_faults_arrow"):
        return "arrow"
    if _has_function(code, "evaluate"):
        return "legacy_row"
    default = os.environ.get("OPEN_FDD_FDD_BACKEND", "arrow").strip() or "arrow"
    return default if default in {"arrow", "legacy_row"} else "arrow"


def legacy_row_allowed(rule: dict[str, Any] | None = None) -> bool:
    rule = rule or {}
    if str(rule.get("backend") or "").strip() == "legacy_row":
        return True
    return os.environ.get("OPEN_FDD_FDD_BACKEND", "").strip() == "legacy_row"


def migrate_legacy_threshold_hint(code: str, cfg: dict[str, Any]) -> str | None:
    """Starter Arrow template for simple ``evaluate`` threshold rules."""
    if not _has_function(code, "evaluate") or _has_function(code, "apply_faults_arrow"):
        return None
    col = str(cfg.get("value_column") or cfg.get("column") or "zone_temp")
    key = "max_zone_temp"
    for k, v in cfg.items():
        if isinstance(v, (int, float)) and k not in {"rolling_avg_minutes"}:
            key = k
            break
    return f'''import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["{col}"], cfg["{key}"])
'''
