"""Unit tests for site_resolver.resolve_site_uuid."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from open_fdd.platform.site_resolver import resolve_site_uuid


def _mock_conn(fetchone=None, fetchall=None):
    """Build a mock DB connection."""
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.rowcount = 1
    cursor.fetchone.return_value = fetchone
    if fetchall is not None:
        cursor.fetchall.return_value = (
            fetchall if isinstance(fetchall, list) else [fetchall]
        )
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    return conn


def test_resolve_site_uuid_by_uuid():
    """Existing site found by UUID returns its id."""
    site_id = uuid4()
    row = {"id": site_id}
    conn = _mock_conn(fetchone=row)
    with patch("open_fdd.platform.site_resolver.get_conn", side_effect=lambda: conn):
        result = resolve_site_uuid(str(site_id), create_if_empty=False)
    assert result == site_id


def test_resolve_site_uuid_by_name():
    """Existing site found by name returns its id."""
    site_id = uuid4()
    row = {"id": site_id}
    conn = _mock_conn(fetchone=row)
    with patch("open_fdd.platform.site_resolver.get_conn", side_effect=lambda: conn):
        result = resolve_site_uuid("Default", create_if_empty=False)
    assert result == site_id


def test_resolve_site_uuid_not_found_other_sites_exist():
    """When not found by id/name but other sites exist, return first site."""
    site_id = uuid4()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchone.side_effect = [None, {"id": site_id}]
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    with patch("open_fdd.platform.site_resolver.get_conn", side_effect=lambda: conn):
        result = resolve_site_uuid("unknown", create_if_empty=False)
    assert result == site_id


def test_resolve_site_uuid_not_found_empty_table_create_false():
    """When not found and table is empty, create_if_empty=False returns None."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchone.return_value = None  # both queries return None
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    with patch("open_fdd.platform.site_resolver.get_conn", side_effect=lambda: conn):
        result = resolve_site_uuid("new-site", create_if_empty=False)
    assert result is None


def test_resolve_site_uuid_not_found_empty_table_create_true():
    """When not found and table is empty, create_if_empty=True creates and returns site."""
    site_id = uuid4()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.return_value = None
    cursor.fetchone.side_effect = [None, None, {"id": site_id}]
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    conn.commit = MagicMock()
    with patch("open_fdd.platform.site_resolver.get_conn", side_effect=lambda: conn):
        result = resolve_site_uuid("new-site", create_if_empty=True)
    assert result == site_id
    cursor.execute.assert_called()
    conn.commit.assert_called_once()
