"""Compatibility shim: implementation moved to ``open_fdd.gateway.server``."""

from open_fdd.gateway.cli import run_desktop_bridge, run_gateway
from open_fdd.gateway.server import create_app

__all__ = ["create_app", "run_desktop_bridge", "run_gateway"]
