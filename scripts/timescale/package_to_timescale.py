#!/usr/bin/env python3
"""Lab helper: Open-FDD package folder → Timescale (compose/seed path).

Not product runtime. Mirrors auto_seed_fast for any building package dir.
Does not delete existing site rows. A replace requires OPENFDD_SEED_FORCE=1
and OPENFDD_ALLOW_DESTRUCTIVE_DB=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

pkg = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPENFDD_SEED_BUILDING50_DIR", "."))
os.environ["OPENFDD_SEED_BUILDING50_DIR"] = str(pkg.resolve())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_seed_fast import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
