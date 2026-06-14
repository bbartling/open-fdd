"""Tests for RCx Central → Edge proxy helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from portfolio.central.rcx_proxy import rcx_preview, rcx_report, rcx_workspace


@patch("portfolio.central.rcx_proxy.EdgeClient")
@patch("portfolio.central.rcx_proxy.resolve_token", return_value="tok")
@patch("portfolio.central.rcx_proxy.resolve_site_config")
def test_rcx_preview_proxies_to_edge(mock_site, _tok, mock_client_cls):
    mock_site.return_value = MagicMock(name="ACME", base_url="http://edge.test")
    client = mock_client_cls.return_value
    client.post_rcx_preview.return_value = {"site_id": "acme", "available_charts": []}

    out = rcx_preview("acme", {"hours": 24, "catalog_only": True})
    assert out["site_id"] == "acme"
    client.post_rcx_preview.assert_called_once()
    body = client.post_rcx_preview.call_args[0][0]
    assert body["site_id"] == "acme"
    assert body["hours"] == 24


@patch("portfolio.central.rcx_proxy.EdgeClient")
@patch("portfolio.central.rcx_proxy.resolve_token", return_value="tok")
@patch("portfolio.central.rcx_proxy.resolve_site_config")
def test_rcx_workspace_proxies_to_edge(mock_site, _tok, mock_client_cls):
    mock_site.return_value = MagicMock(name="ACME", base_url="http://edge.test")
    client = mock_client_cls.return_value
    client.get_rcx_workspace.return_value = {"catalog": {}, "point_tree": {}}

    out = rcx_workspace("acme", hours=48)
    assert "catalog" in out
    client.get_rcx_workspace.assert_called_once_with(
        "acme",
        hours=48,
        start=None,
        end=None,
        show_fault_overlays=True,
        token="tok",
    )


@patch("portfolio.central.rcx_proxy.EdgeClient")
@patch("portfolio.central.rcx_proxy.resolve_token", return_value="tok")
@patch("portfolio.central.rcx_proxy.resolve_site_config")
def test_rcx_report_returns_docx_bytes(mock_site, _tok, mock_client_cls):
    mock_site.return_value = MagicMock(name="ACME", base_url="http://edge.test")
    client = mock_client_cls.return_value
    client.post_rcx_generate.return_value = (b"PK\x03\x04", "openfdd-rcx-acme.docx")

    blob, fname = rcx_report("acme", {"hours": 24, "sections": ["executive_summary"]})
    assert blob[:2] == b"PK"
    assert fname.endswith(".docx")
