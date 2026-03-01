"""
Graph-based site discovery for the Open-FDD HA integration.

Open-FDD is a graph-based RDF platform: config, sites, equipment, and points
live in the knowledge graph (serialized to config/data_model.ttl). This module
uses POST /data-model/sparql to query brick:Site and create HA devices from
the graph so the integration reflects the RDF model rather than inferring
sites only from fault payloads.
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Brick sites query: same as used by graph_and_crud_test and API docs.
SPARQL_SITES = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }
"""


def _site_uri_to_id(site_uri: str) -> str | None:
    """Extract site UUID from graph site URI (e.g. http://openfdd.local/site#site_abc_def_...)."""
    if not site_uri or "#" not in site_uri:
        return None
    fragment = site_uri.split("#", 1)[1].strip()
    if not fragment.startswith("site_"):
        return None
    # site_<uuid_with_underscores> -> UUID with dashes
    return fragment[5:].replace("_", "-")


def _parse_binding_value(b: dict[str, Any], key: str) -> str | None:
    """Get string value from a SPARQL binding; API returns plain dict with string values."""
    v = b.get(key)
    if v is None:
        return None
    return str(v).strip() or None


async def fetch_sites_from_graph(client) -> list[tuple[str, str]]:
    """
    Query the Open-FDD graph for brick:Sites via POST /data-model/sparql.
    Returns list of (site_id, site_label) for each site. site_id is the UUID
    used by the API (faults, CRUD); site_label is the human-readable name.
    """
    try:
        result = await client.post_data_model_sparql(SPARQL_SITES)
    except Exception as e:
        _LOGGER.debug("SPARQL sites query failed (graph may be empty): %s", e)
        return []
    bindings = result.get("bindings") if isinstance(result, dict) else []
    if not bindings:
        return []
    out: list[tuple[str, str]] = []
    for row in bindings:
        site_uri = _parse_binding_value(row, "site")
        site_label = _parse_binding_value(row, "site_label")
        site_id = _site_uri_to_id(site_uri) if site_uri else None
        if site_id and site_label:
            out.append((site_id, site_label))
    return out


async def ensure_site_devices_from_graph(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client,
) -> None:
    """
    Ensure HA devices exist for every site in the Open-FDD graph.
    Uses SPARQL so device layout is driven by the RDF model (no constant files).
    Fault entities still attach to these devices by site_id when faults appear.
    """
    sites = await fetch_sites_from_graph(client)
    if not sites:
        return
    device_registry = dr.async_get(hass)
    for site_id, site_label in sites:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, site_id)},
            manufacturer="Open-FDD",
            model="Open-FDD Platform",
            name=f"Open-FDD {site_label}",
        )
    _LOGGER.debug("Ensured %d site device(s) from graph", len(sites))
