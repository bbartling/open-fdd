"""Shim: rebind to open_fdd.rules.pid_hunting (PyPI open-fdd)."""
import open_fdd.rules.pid_hunting as _impl
import sys as _sys
_sys.modules[__name__] = _impl
