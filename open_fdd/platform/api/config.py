"""Config API: GET/PUT platform config (RDF in same graph as Brick + BACnet, SPARQL via POST /data-model/sparql)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from open_fdd.platform.config import get_config_overlay, set_config_overlay
from open_fdd.platform.default_config import DEFAULT_PLATFORM_CONFIG
from open_fdd.platform.graph_model import (
    get_config_from_graph,
    set_config_in_graph,
    write_ttl_to_file,
)

router = APIRouter(prefix="/config", tags=["config"])

# Allowed keys for PUT (subset of PlatformSettings that live in RDF)
CONFIG_KEYS = {
    "rule_interval_hours",
    "lookback_days",
    "rules_dir",
    "brick_ttl_dir",
    "bacnet_enabled",
    "bacnet_scrape_interval_min",
    "bacnet_server_url",
    "bacnet_site_id",
    "bacnet_gateways",
    "open_meteo_enabled",
    "open_meteo_interval_hours",
    "open_meteo_latitude",
    "open_meteo_longitude",
    "open_meteo_timezone",
    "open_meteo_days_back",
    "open_meteo_site_id",
    "graph_sync_interval_min",
}


class ConfigBody(BaseModel):
    """Platform config (RDF-backed). Omitted keys are left unchanged."""

    rule_interval_hours: float | None = Field(None, description="FDD rule run interval (hours)")
    lookback_days: int | None = Field(None, description="Days of data per FDD run")
    rules_dir: str | None = Field(None, description="Path to FDD rules YAML")
    brick_ttl_dir: str | None = Field(None, description="Directory for Brick TTL")
    bacnet_enabled: bool | None = Field(None, description="Enable BACnet scraper")
    bacnet_scrape_interval_min: int | None = Field(None, description="BACnet scrape interval (minutes)")
    bacnet_server_url: str | None = Field(None, description="diy-bacnet-server URL")
    bacnet_site_id: str | None = Field(None, description="Default site for BACnet scrape")
    bacnet_gateways: str | None = Field(None, description="JSON array of gateways")
    open_meteo_enabled: bool | None = Field(None, description="Enable Open-Meteo fetch")
    open_meteo_interval_hours: int | None = Field(None, description="Weather fetch interval (hours)")
    open_meteo_latitude: float | None = Field(None, description="Latitude")
    open_meteo_longitude: float | None = Field(None, description="Longitude")
    open_meteo_timezone: str | None = Field(None, description="Timezone")
    open_meteo_days_back: int | None = Field(None, description="Days of weather to fetch")
    open_meteo_site_id: str | None = Field(None, description="Site for weather points")
    graph_sync_interval_min: int | None = Field(None, description="Graph sync to TTL (minutes)")


@router.get("", summary="Get platform config")
def get_config():
    """Return current platform config from the knowledge graph (same as used by SPARQL). When graph has no config, returns DEFAULT_PLATFORM_CONFIG."""
    overlay = get_config_overlay()
    if overlay:
        return overlay
    from_graph = get_config_from_graph()
    if from_graph:
        return from_graph
    return dict(DEFAULT_PLATFORM_CONFIG)


@router.put("", summary="Set platform config (RDF + TTL)")
def put_config(body: ConfigBody):
    """Update platform config in the graph and serialize to config/data_model.ttl. Omitted keys are unchanged."""
    overlay = get_config_overlay()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        # No changes; still persist current overlay to graph if any
        if overlay:
            set_config_in_graph(overlay)
            ok, err = write_ttl_to_file()
            if not ok:
                raise HTTPException(500, f"Failed to write TTL: {err}")
        return get_config()

    merged = dict(overlay)
    for k, v in updates.items():
        if k in CONFIG_KEYS:
            merged[k] = v
    set_config_in_graph(merged)
    ok, err = write_ttl_to_file()
    if not ok:
        raise HTTPException(500, f"Failed to write TTL: {err}")
    set_config_overlay(merged)
    return merged
