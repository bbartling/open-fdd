"""Shim: rebind to open_fdd.rules.sensor_rate (PyPI open-fdd)."""
import open_fdd.rules.sensor_rate as _impl
import sys as _sys
_sys.modules[__name__] = _impl
