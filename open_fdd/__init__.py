"""
open-fdd — embeddable Arrow-native HVAC fault detection runtime.

Use the PyPI package to lint, test, and run ``apply_faults_arrow(table, cfg, context)``
against PyArrow / Feather / Parquet batches in your own pipelines.

The full BACnet bridge, dashboard, MCP agent, and edge deploy stack ships as
GHCR Docker images (``openfdd-bridge``, ``openfdd-commission``, ``openfdd-mcp-rag``),
not inside this wheel.
"""

__version__ = "3.1.5"

__all__ = ["__version__"]
