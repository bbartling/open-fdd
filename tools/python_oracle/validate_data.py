#!/usr/bin/env python3
"""Legacy Vibe19 validate entry — retired for product path.

Use Open-FDD package ingest / central APIs instead. This stub fails loudly
so CI/agents do not silently depend on removed ``shared.*`` modules.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "FAIL: tools/python_oracle/validate_data.py is retired (Vibe19 shared.* removed).\n"
        "Use package import + /api/csv/import/package, or scripts/sql_pandas_oracle_check.py.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
