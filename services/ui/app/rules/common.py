"""Shim: rebind to open_fdd.rules.common (PyPI open-fdd)."""
import open_fdd.rules.common as _impl
import sys as _sys
_sys.modules[__name__] = _impl
