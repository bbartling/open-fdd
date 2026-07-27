"""Shim: rebind to open_fdd.rules.custom_boilerplate (PyPI open-fdd)."""
import open_fdd.rules.custom_boilerplate as _impl
import sys as _sys
_sys.modules[__name__] = _impl
