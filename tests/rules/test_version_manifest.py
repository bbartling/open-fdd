"""Independent version axes and deprecated extra alias."""

from __future__ import annotations

import json
import warnings

from open_fdd import __version__, manifest
from open_fdd.version import python_version, rust_engine_version


def test_manifest_has_independent_axes():
    doc = manifest()
    assert doc["open_fdd_python_version"] == __version__ == python_version()
    assert set(doc) >= {
        "open_fdd_python_version",
        "git_revision",
        "rust_engine_version",
        "rule_catalog_version",
        "catalog_schema_version",
        "rule_catalog_hash",
        "effective_config_hash",
    }
    rust = rust_engine_version()
    if rust is not None:
        assert rust == doc["rust_engine_version"]
        assert rust.startswith("3.")


def test_manifest_json_roundtrip():
    blob = json.dumps(manifest(), sort_keys=True)
    assert "open_fdd_python_version" in blob
    assert "..." not in blob


def test_vibe19_import_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import importlib

        import open_fdd.vibe19 as mod

        importlib.reload(mod)
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations
    assert "reporting" in str(deprecations[-1].message)
    assert "5.0" in str(deprecations[-1].message)
