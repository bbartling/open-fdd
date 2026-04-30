"""``desktop_bridge`` re-exports the gateway for backward compatibility."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from open_fdd.desktop_bridge.server import create_app as create_from_shim
from open_fdd.gateway.server import create_app as create_from_gateway


def test_desktop_bridge_shim_matches_gateway() -> None:
    assert create_from_shim is create_from_gateway
