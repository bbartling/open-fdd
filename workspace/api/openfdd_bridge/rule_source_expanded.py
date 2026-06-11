"""Expand rule.py imports to show Open-FDD helper source in Rule Lab."""

from __future__ import annotations

import ast
import importlib
import inspect
from typing import Any

from .rule_source import read_source, resolve_source_path
from .rule_store import RuleStore

_ALLOWLIST_PREFIXES = (
    "open_fdd.",
    "open_fdd_arrow_runtime",
)


def _allowed_module(name: str) -> bool:
    mod = str(name or "").strip()
    if not mod:
        return False
    return any(mod == p.rstrip(".") or mod.startswith(p) for p in _ALLOWLIST_PREFIXES)


def _collect_imports(tree: ast.Module) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, []))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [a.name for a in node.names if a.name != "*"]
            out.append((node.module, names))
    return out


def _read_module_source(module_name: str) -> tuple[str, str]:
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        return "", f"import failed: {exc}"
    try:
        src = inspect.getsource(mod)
        path = str(getattr(mod, "__file__", "") or "")
        return src, path
    except (OSError, TypeError) as exc:
        return "", f"source unavailable: {exc}"


def expand_rule_source(*, rule_id: str) -> dict[str, Any]:
    rule = RuleStore().get(rule_id)
    if not rule:
        return {"ok": False, "error": f"rule not found: {rule_id}"}
    path = str(rule.get("source_path") or "")
    rule_source = read_source(path) if path else str(rule.get("code") or "")
    if not rule_source.strip():
        return {"ok": False, "error": "rule source empty"}

    imports_out: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(rule_source)
    except SyntaxError as exc:
        return {"ok": False, "error": f"syntax error: {exc}"}

    seen: set[str] = set()
    for module_name, symbols in _collect_imports(tree):
        if not _allowed_module(module_name):
            if module_name and module_name not in seen:
                warnings.append(f"skipped non-allowlisted import: {module_name}")
            continue
        if module_name in seen:
            continue
        seen.add(module_name)
        src, note = _read_module_source(module_name)
        entry: dict[str, Any] = {
            "module": module_name,
            "symbols": symbols,
            "source": src,
        }
        if not src:
            entry["warning"] = note
            warnings.append(note)
        imports_out.append(entry)

    return {
        "ok": True,
        "rule_id": rule_id,
        "rule_name": str(rule.get("name") or rule_id),
        "rule_source": rule_source,
        "source_path": path.split("/")[-1] if path else "",
        "imports": imports_out,
        "warnings": warnings,
    }
