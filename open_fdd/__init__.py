"""Open-FDD Python package.

- ``open_fdd.ecm_engineering`` — ECM workbooks (default install)
- ``open_fdd.rules`` / ``analytics`` / ``reporting`` — pandas oracle libs (extras)

Production FDD runs as DataFusion SQL in the GHCR container stack.
"""

from open_fdd.ecm_engineering import ECMJob

__version__ = "4.1.1"

__all__ = ["ECMJob", "__version__"]
