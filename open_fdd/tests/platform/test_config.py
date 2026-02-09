"""Tests for platform config (requires pydantic-settings)."""

import pytest

pytest.importorskip("pydantic_settings")
pytest.importorskip("pydantic")

from open_fdd.platform.config import PlatformSettings, get_platform_settings


def test_platform_settings_defaults():
    """Platform settings have sensible defaults."""
    get_platform_settings.cache_clear()
    try:
        s = get_platform_settings()
        assert s.db_dsn.startswith("postgresql://")
        assert s.rule_interval_hours == 3
        assert s.lookback_days == 3
        assert s.rolling_window == 6
        assert s.bacnet_scrape_interval_min == 5
        assert s.open_meteo_interval_hours == 24
    finally:
        get_platform_settings.cache_clear()
