"""Open-FDD Python package (ECM engineering only on PyPI 4.x).

Production FDD runs as DataFusion SQL in the GHCR container stack.
This wheel ships agent-drivable HVAC spreadsheet calcs under
``open_fdd.ecm_engineering``.
"""

from open_fdd.ecm_engineering import ECMJob

__version__ = "4.0.0"

__all__ = ["ECMJob", "__version__"]
