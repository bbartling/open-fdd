"""Tests for platform config (requires pydantic-settings)."""

import pytest

pytest.importorskip("pydantic_settings")
pytest.importorskip("pydantic")

from open_fdd.platform.config import (
    PlatformSettings,
    get_platform_settings,
    set_config_overlay,
)


def test_default_platform_config_keys_match_api():
    """DEFAULT_PLATFORM_CONFIG only has keys allowed by the config API (CONFIG_KEYS); optional keys like bacnet_gateways may be omitted."""
    from open_fdd.platform.default_config import DEFAULT_PLATFORM_CONFIG
    from open_fdd.platform.api.config import CONFIG_KEYS

    for key in DEFAULT_PLATFORM_CONFIG:
        assert key in CONFIG_KEYS, f"DEFAULT_PLATFORM_CONFIG has extra key not in CONFIG_KEYS: {key}"
    # All non-optional defaults that GET /config should expose when graph is empty
    assert "brick_ttl_dir" in DEFAULT_PLATFORM_CONFIG
    assert "rule_interval_hours" in DEFAULT_PLATFORM_CONFIG
    assert "bacnet_server_url" in DEFAULT_PLATFORM_CONFIG


def test_default_platform_config_values():
    """DEFAULT_PLATFORM_CONFIG has expected default values (brick_ttl_dir, rule_interval_hours, etc.)."""
    from open_fdd.platform.default_config import (
        DEFAULT_PLATFORM_CONFIG,
        DEFAULT_BRICK_TTL_DIR,
        DEFAULT_RULE_INTERVAL_HOURS,
        DEFAULT_BACNET_SERVER_URL,
        DEFAULT_GRAPH_SYNC_INTERVAL_MIN,
    )

    assert DEFAULT_PLATFORM_CONFIG["brick_ttl_dir"] == DEFAULT_BRICK_TTL_DIR == "config"
    assert DEFAULT_PLATFORM_CONFIG["rule_interval_hours"] == DEFAULT_RULE_INTERVAL_HOURS == 0.1
    assert DEFAULT_PLATFORM_CONFIG["bacnet_server_url"] == DEFAULT_BACNET_SERVER_URL == "http://localhost:8080"
    assert DEFAULT_PLATFORM_CONFIG["graph_sync_interval_min"] == DEFAULT_GRAPH_SYNC_INTERVAL_MIN == 5
    assert DEFAULT_PLATFORM_CONFIG["rules_dir"] == "analyst/rules"
    assert DEFAULT_PLATFORM_CONFIG["bacnet_enabled"] is True
    assert DEFAULT_PLATFORM_CONFIG["open_meteo_timezone"] == "America/Chicago"


def test_get_config_returns_default_when_graph_empty():
    """When overlay and graph have no config, GET /config behavior returns DEFAULT_PLATFORM_CONFIG from code."""
    from unittest.mock import patch

    from open_fdd.platform.api.config import get_config
    from open_fdd.platform.default_config import DEFAULT_PLATFORM_CONFIG

    set_config_overlay({})
    with patch("open_fdd.platform.api.config.get_config_from_graph", return_value={}):
        result = get_config()
    assert result == DEFAULT_PLATFORM_CONFIG
    set_config_overlay({})


def test_platform_settings_defaults():
    """Platform settings have sensible defaults (env only when overlay empty)."""
    set_config_overlay({})
    s = get_platform_settings()
    assert s.db_dsn.startswith("postgresql://")
    assert s.rule_interval_hours == 3.0
    assert s.lookback_days == 3
    assert s.bacnet_scrape_interval_min == 5
    assert s.open_meteo_interval_hours == 24
    assert s.open_meteo_latitude == 41.88
    assert s.open_meteo_longitude == -87.63
    assert s.open_meteo_site_id == "default"


def test_platform_settings_overlay():
    """Overlay overrides env for runtime config."""
    set_config_overlay({})
    s = get_platform_settings()
    assert s.rule_interval_hours == 3.0
    set_config_overlay({"rule_interval_hours": 0.1, "bacnet_server_url": "http://localhost:8080"})
    s2 = get_platform_settings()
    assert s2.rule_interval_hours == 0.1
    assert s2.bacnet_server_url == "http://localhost:8080"
    set_config_overlay({})
