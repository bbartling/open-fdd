"""ColumnMapResolver protocol and BrickTtlColumnMapResolver parity with resolve_from_ttl."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("rdflib")

from open_fdd.engine.brick_resolver import resolve_from_ttl
from open_fdd.engine.column_map_resolver import BrickTtlColumnMapResolver, ColumnMapResolver
from open_fdd.tests.engine.test_brick_resolver import _MINIMAL_TTL


def _mock_conn_no_sites():
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def test_brick_ttl_resolver_matches_resolve_from_ttl(tmp_path):
    """Default resolver must match historical resolve_from_ttl(ttl_path) behavior."""
    ttl_file = tmp_path / "model.ttl"
    ttl_file.write_text(_MINIMAL_TTL)
    expected = resolve_from_ttl(ttl_file)
    got = BrickTtlColumnMapResolver().build_column_map(ttl_path=ttl_file)
    assert got == expected


def test_brick_ttl_resolver_empty_when_ttl_missing(tmp_path):
    """Missing TTL file yields empty map (same as prior loop behavior)."""
    missing = tmp_path / "nope.ttl"
    assert not missing.exists()
    assert BrickTtlColumnMapResolver().build_column_map(ttl_path=missing) == {}


def test_column_map_resolver_protocol_runtime_check():
    """BrickTtlColumnMapResolver satisfies ColumnMapResolver protocol."""
    r = BrickTtlColumnMapResolver()
    assert isinstance(r, ColumnMapResolver)
