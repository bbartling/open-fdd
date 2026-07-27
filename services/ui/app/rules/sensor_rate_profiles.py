"""Shim: rebind to open_fdd.rules.sensor_rate_profiles (PyPI open-fdd)."""
import open_fdd.rules.sensor_rate_profiles as _impl
import sys as _sys
_sys.modules[__name__] = _impl
