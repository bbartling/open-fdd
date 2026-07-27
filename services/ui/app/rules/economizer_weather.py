"""Shim: rebind to open_fdd.rules.economizer_weather (PyPI open-fdd)."""
import open_fdd.rules.economizer_weather as _impl
import sys as _sys
_sys.modules[__name__] = _impl
