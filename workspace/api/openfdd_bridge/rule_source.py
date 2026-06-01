"""On-disk Python rule sources — AI agents and the browser edit the same .py file."""

from __future__ import annotations

import re
from pathlib import Path

from .paths import data_dir

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def rules_py_dir() -> Path:
    path = data_dir() / "rules_py"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slug_rule_name(name: str, rule_id: str) -> str:
    base = _SAFE.sub("_", str(name or "").strip()).strip("_").lower()
    if not base:
        base = f"rule_{str(rule_id)[:8]}"
    return base[:48]


def rule_py_path(*, rule_id: str, name: str) -> Path:
    return rules_py_dir() / f"{slug_rule_name(name, rule_id)}.py"


def read_source(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def write_source(*, rule_id: str, name: str, code: str, existing_path: str | None = None) -> str:
    target = Path(existing_path) if existing_path else rule_py_path(rule_id=rule_id, name=name)
    rules_root = rules_py_dir().resolve(strict=False)
    try:
        resolved = target.resolve(strict=False)
        if resolved != rules_root and rules_root not in resolved.parents:
            target = rule_py_path(rule_id=rule_id, name=name)
    except OSError:
        target = rule_py_path(rule_id=rule_id, name=name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    return str(target)
