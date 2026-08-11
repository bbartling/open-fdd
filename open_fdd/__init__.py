"""Open-FDD Python package.

- ``open_fdd.ecm_engineering`` — ECM workbooks (default install)
- ``open_fdd.rules`` / ``analytics`` / ``reporting`` — pandas oracle libs (extras)

Production FDD runs as DataFusion SQL in the GHCR container stack.
"""

from open_fdd.ecm_engineering import ECMJob
from open_fdd.compat import maybe_warn_vibe19_from_env

__version__ = "4.3.0"

maybe_warn_vibe19_from_env()

__all__ = ["ECMJob", "__version__", "manifest"]


def manifest(**kwargs):
    from open_fdd.version import manifest as _manifest

    return _manifest(**kwargs)
