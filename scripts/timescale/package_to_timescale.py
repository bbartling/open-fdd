#!/usr/bin/env python3
"""Lab helper: Open-FDD package folder → Timescale (compose/seed path).

Not product runtime. Mirrors auto_seed_fast for any building package dir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Reuse fast seeder by pointing B50 env at the package root.
# Do not force a reload. Occupied databases refuse unless the operator sets
# OPENFDD_SEED_FORCE=1 and OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
pkg = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPENFDD_SEED_BUILDING50_DIR", "."))
os.environ["OPENFDD_SEED_BUILDING50_DIR"] = str(pkg.resolve())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_seed_fast import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
