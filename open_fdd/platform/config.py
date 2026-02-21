"""Platform configuration."""

from functools import lru_cache
from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings  # type: ignore


class PlatformSettings(BaseSettings):
    """App settings from env."""

    db_dsn: str = "postgresql://postgres:postgres@localhost:5432/openfdd"
    brick_ttl_dir: str = "data/brick"
    brick_ttl_path: str = (
        "config/brick_model.ttl"  # auto-synced on CRUD; FDD loop reads this
    )
    app_title: str = "Open-FDD API"
    app_version: str = "2.0.1"
    debug: bool = False

    # FDD loop
    rule_interval_hours: float = 3.0  # fractional OK for testing (e.g. 0.1 = 6 min)
    lookback_days: int = 3
    fdd_trigger_file: Optional[str] = (
        "config/.run_fdd_now"  # touch to run now + reset timer
    )
    rules_dir: str = (
        "analyst/rules"  # single place for project rules (hot reload each run)
    )

    # Driver intervals
    bacnet_scrape_interval_min: int = 5
    open_meteo_interval_hours: int = 24

    # Driver on/off (like Volttron agent enable/disable)
    bacnet_scrape_enabled: bool = True
    open_meteo_enabled: bool = True

    # Open-Meteo: geo and fetch window (used when open_meteo_enabled)
    open_meteo_latitude: float = 41.88
    open_meteo_longitude: float = -87.63
    open_meteo_timezone: str = "America/Chicago"
    open_meteo_days_back: int = 3
    open_meteo_site_id: str = "default"  # site name or UUID to store weather under

    # Graph model: sync in-memory graph to brick_model.ttl every N minutes
    graph_sync_interval_min: int = 5

    # BACnet: use diy-bacnet-server JSON-RPC when set (e.g. http://localhost:8080)
    bacnet_server_url: Optional[str] = None
    # Site to tag when scraping (single gateway or remote gateway pushing to central)
    bacnet_site_id: str = "default"
    # Optional: multiple gateways (central aggregator). JSON array of {"url", "site_id", "config_csv"}
    bacnet_gateways: Optional[str] = None
    # Prefer data-model scrape over CSV when points have BACnet addressing (fall back to CSV if no points)
    bacnet_use_data_model: bool = True

    model_config = {"env_prefix": "OFDD_", "env_file": ".env"}


@lru_cache
def get_platform_settings() -> PlatformSettings:
    return PlatformSettings()
