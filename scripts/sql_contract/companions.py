"""Companion assets bound to the scientific pack but outside the 110-file ledger."""

from __future__ import annotations

from pathlib import Path

# Renderer/binder + tuning defaults (paths relative to repo / artifact root).
COMPANION_RELPATHS: tuple[str, ...] = (
    "sql/fdd/tuning_catalog.json",
    "sql/fdd/runtime_defaults.json",
    "sql/fdd/render_rule.py",
)

SCHEMA_INSTALL_ORDER: tuple[str, ...] = (
    "sql/schema/00_extensions.sql",
    "sql/schema/01_bps_core.sql",
    "sql/schema/02_openfdd_dims.sql",
    "sql/schema/03_wide_history_helper.sql",
    "sql/schema/05_portal_inventory.sql",
    "sql/schema/11_point_map_binding_metadata.sql",
    "sql/schema/07_opaque_series_binding.sql",
)

POSTGRES_HELPERS = "sql/fdd/postgres/postgres_helpers.sql"
ANALYTICS_QUERIES_DIR = "sql/analytics/postgres/queries"
ANALYTICS_REGISTRY = "sql/analytics/registry.json"
FDD_REGISTRY = "sql/fdd/registry.yaml"


def companion_paths(root: Path) -> list[Path]:
    return [root / rel for rel in COMPANION_RELPATHS]
