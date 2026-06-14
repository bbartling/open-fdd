from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
for p in (str(REPO), str(API_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
