"""Platform configuration.

Runtime config can come from env (OFDD_*) or from the RDF graph (PUT /config).
When the graph has config, it overrides env for those keys. Overlay is populated
on API startup from data_model.ttl and on PUT /config.
"""

from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings  # type: ignore

# Overlay from RDF graph (GET/PUT /config). Merged over env in get_platform_settings().
_config_overlay: dict = {}


def set_config_overlay(overlay: dict | None) -> None:
    """Set the config overlay (from graph). Called after load_from_file() and on PUT /config."""
    global _config_overlay
    _config_overlay = dict(overlay) if overlay else {}


def get_config_overlay() -> dict:
    """Return current overlay (snake_case keys)."""
    return dict(_config_overlay)


class PlatformSettings(BaseSettings):
    """App settings from env."""

    db_dsn: str = "postgresql://postgres:postgres@localhost:5432/openfdd"
    brick_ttl_dir: str = "data/brick"
    brick_ttl_path: str = (
        "config/data_model.ttl"  # unified graph: Brick + BACnet + config; auto-synced on CRUD
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

    # Graph model: sync in-memory graph to data_model.ttl every N minutes
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


def get_platform_settings() -> PlatformSettings:
    """Effective settings: env first, then overlay from RDF (PUT /config). Not cached so overlay is visible."""
    s = PlatformSettings()
    for k, v in get_config_overlay().items():
        if hasattr(s, k):
            setattr(s, k, v)
    return s
