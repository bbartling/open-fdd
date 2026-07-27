"""Shim: rebind to open_fdd.rules.runner (PyPI open-fdd)."""
import open_fdd.rules.runner as _impl
import sys as _sys
_sys.modules[__name__] = _impl
