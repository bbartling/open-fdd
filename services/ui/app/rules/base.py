"""Shim: rebind to open_fdd.rules.base (PyPI open-fdd)."""
import open_fdd.rules.base as _impl
import sys as _sys
_sys.modules[__name__] = _impl
