"""ColumnMapResolver protocol (manifest-based; engine has no RDF)."""

from pathlib import Path

from open_fdd.engine.column_map_resolver import ColumnMapResolver, ManifestColumnMapResolver


def test_manifest_resolver_satisfies_protocol_runtime_check(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("k: v\n", encoding="utf-8")
    r = ManifestColumnMapResolver(p)
    assert isinstance(r, ColumnMapResolver)
