"""Build BRICK TTL from exported model.json (same logic as Edge ttl_service)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _bridge_root() -> Path:
    return Path(__file__).resolve().parents[2] / "workspace" / "api"


def build_ttl_from_model(model: dict[str, Any]) -> str:
    """Generate Turtle from in-memory model export dict."""
    bridge_api = _bridge_root()
    bridge_str = str(bridge_api)
    if bridge_str not in sys.path:
        sys.path.insert(0, bridge_str)

    from openfdd_bridge.ttl_service import TtlService

    class _MemoryStore:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def load(self) -> dict[str, Any]:
            return self._payload

    return TtlService(model_store=_MemoryStore(model)).build_ttl()
