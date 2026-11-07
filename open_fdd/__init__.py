"""Open-FDD Python package (PyPI ``open-fdd``): the AI-agent and engineer toolbox.

- ``open_fdd.nf``  - read a Normal Framework box (LAN or portal), SI frames, run the pandas rules
- ``open_fdd.rules`` / ``analytics`` / ``reporting`` - pandas reference rules and reports (extras)
- ``open_fdd.ecm_engineering`` - ECM workbooks (default install)

Production FDD runs in the Open-FDD Normal Framework app (SQL pack). This package's version line
(4.x) is separate from the app's (5.x); see ``open-fdd-version``.
"""

from open_fdd.ecm_engineering import ECMJob
from open_fdd.version import package_version

__version__ = package_version()

__all__ = ["ECMJob", "__version__", "manifest"]


def manifest(**kwargs):
    from open_fdd.version import manifest as _manifest

    return _manifest(**kwargs)
