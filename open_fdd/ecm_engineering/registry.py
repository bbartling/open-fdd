from __future__ import annotations
from collections.abc import Callable
from typing import Any

Calculator = Callable[[dict[str, Any]], dict[str, Any]]
_REGISTRY: dict[str, Calculator] = {}

def register(name: str):
    def deco(fn: Calculator) -> Calculator:
        if name in _REGISTRY:
            raise RuntimeError(f"calculator already registered: {name}")
        _REGISTRY[name] = fn
        return fn
    return deco

def get(name: str) -> Calculator:
    if name not in _REGISTRY:
        raise KeyError(f"unknown calculator {name!r}; available={sorted(_REGISTRY)}")
    return _REGISTRY[name]

def names() -> list[str]:
    return sorted(_REGISTRY)
