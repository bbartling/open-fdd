"""Shared helpers for Open-FDD Soft-OPEN SPARQL lessons.

Thin re-export of ``scripts/stress/helpers`` so lesson scripts share the same
Windows-friendly ``--host`` / JWT connection style as the stress gate.

  python scripts/lessons/lesson_01_sites_and_equipment.py --host <lab-ip>

Env: OPENFDD_API_BASE / OPENFDD_STRESS_BASE, OPENFDD_AGENT_PASSWORD,
OPENFDD_STRESS_BUILDING_ID. Synthetic sites only.
"""

from __future__ import annotations

import sys
from pathlib import Path

_STRESS = Path(__file__).resolve().parents[1] / "stress"
if str(_STRESS) not in sys.path:
    sys.path.insert(0, str(_STRESS))

from helpers import (  # noqa: E402,F401
    DEFAULT_BUILDING_ID,
    DEFAULT_LOCAL,
    DEFAULT_PASS,
    DEFAULT_PORT,
    DEFAULT_USER,
    HttpClient,
    add_connection_args,
    apply_base_url,
    banner,
    client,
    configure_stdio,
    ensure_repo_on_path,
    get_package_ttl,
    get_sparql_catalog,
    get_timeseries_readings,
    historian_query,
    login,
    mint_opaque_point_iri,
    parse_connection,
    point_resolve,
    post_sparql,
    print_table,
    require_building_id,
    resolve_base_url,
    safe_print,
    short,
    wait_until_ready,
)

__all__ = [
    "DEFAULT_BUILDING_ID",
    "DEFAULT_LOCAL",
    "DEFAULT_PASS",
    "DEFAULT_PORT",
    "DEFAULT_USER",
    "HttpClient",
    "add_connection_args",
    "apply_base_url",
    "banner",
    "client",
    "configure_stdio",
    "ensure_repo_on_path",
    "get_package_ttl",
    "get_sparql_catalog",
    "get_timeseries_readings",
    "historian_query",
    "login",
    "mint_opaque_point_iri",
    "parse_connection",
    "point_resolve",
    "post_sparql",
    "print_table",
    "require_building_id",
    "resolve_base_url",
    "safe_print",
    "short",
    "wait_until_ready",
]
