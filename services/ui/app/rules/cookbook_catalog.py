"""Shim: rebind to open_fdd.rules.cookbook_catalog (PyPI open-fdd)."""
import open_fdd.rules.cookbook_catalog as _impl
import sys as _sys
_sys.modules[__name__] = _impl
