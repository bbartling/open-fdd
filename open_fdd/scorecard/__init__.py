"""Portable FDD rule scorecard: score any rule_result-style table against fault labels (stdlib only).

Works standalone (``pip install open-fdd``): no Normal Framework, no Open-FDD app, no pandas. The same SQL
(:data:`SQL_PATH`) runs inside PostgreSQL / TimescaleDB / SQLite, and :func:`score` runs it on CSV exports in an
in-memory SQLite database.
"""

from open_fdd.scorecard.core import (
    SQL_PATH,
    Config,
    load_config,
    score,
    wilson_interval,
)

__all__ = ["SQL_PATH", "Config", "load_config", "score", "wilson_interval"]
