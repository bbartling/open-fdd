"""Shim: rebind to open_fdd.rules.operational_gate (PyPI open-fdd)."""
import open_fdd.rules.operational_gate as _impl
import sys as _sys
_sys.modules[__name__] = _impl
