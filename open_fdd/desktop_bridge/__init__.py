"""Compatibility shim: prefer ``import open_fdd.gateway`` or ``open_fdd.gateway.server``."""

from open_fdd.gateway.cli import run_desktop_bridge, run_gateway

__all__ = ["run_desktop_bridge", "run_gateway"]
