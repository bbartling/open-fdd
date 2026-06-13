"""Local BRICK SPARQL buttons for RCx Central Data Model tab."""

from __future__ import annotations

SPARQL_BUTTONS: list[tuple[str, str]] = [
    ("sync_ttl", "Sync TTL → Central"),
    ("validate", "Validate SPARQL model"),
    ("ahu_information", "Count AHUs (SPARQL)"),
    ("count-vavs", "Count VAVs (SPARQL)"),
    ("sites", "List sites (SPARQL)"),
]
