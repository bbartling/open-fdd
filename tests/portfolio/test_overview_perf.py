"""Tests for overview cache and fast overview path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from portfolio.central.overview_cache import cache_ttl_seconds, get_or_set, invalidate_prefix


def test_cache_get_or_set_hit():
    invalidate_prefix("test:")
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return {"v": calls["n"]}

    a, hit_a = get_or_set("test:key", 60, builder)
    b, hit_b = get_or_set("test:key", 60, builder)
    assert a == b == {"v": 1}
    assert hit_a is False
    assert hit_b is True
    assert calls["n"] == 1


def test_cache_ttl_disabled():
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return 1

    get_or_set("test:off", 0, builder)
    get_or_set("test:off", 0, builder)
    assert calls["n"] == 2


def test_cache_ttl_seconds_default():
    assert cache_ttl_seconds() >= 0


@patch("portfolio.central.building_summary.build_building_summary")
@patch("portfolio.central.edge_fetch.edge_client_for_site")
def test_build_overview_fast_parallel(mock_edge_for_site, mock_summary):
    from portfolio.central.overview_data import build_overview

    client = MagicMock()
    client.get_faults_status.return_value = {"alert_count": 2, "families": [], "traffic": "green"}
    client.get_portfolio_rollup.return_value = {"overrides": {"operator_override_points": 0, "points": []}}
    mock_edge_for_site.return_value = (MagicMock(name="Acme"), "tok", client)
    mock_summary.return_value = {
        "narrative": "Fast summary",
        "counts": {"ahus": 1, "vavs": 2, "zones": 0},
        "brick_site_id": "acme",
        "brick_site_name": "Acme",
        "registry_name": "Acme",
        "feeds_chains": [],
        "model_equipment": 3,
        "model_points": 10,
    }

    out = build_overview("acme", include_live=True, fast=True)
    assert out.get("fast_mode") is True
    assert out.get("mechanical_narrative") == "Fast summary"
    assert out.get("connection_ok") is True
    client.get_faults_status.assert_called_once()
    mock_summary.assert_called_once_with("acme", fast=True)
