#!/usr/bin/env bash
# Sanity-check supervisor/manifest.yaml vs docker/Dockerfile targets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
manifest = (root / "supervisor/manifest.yaml").read_text()
dockerfile = (root / "docker/Dockerfile").read_text()
apps = re.findall(r"build_target:\s*(\w+)", manifest)
for t in apps:
    if f"AS {t}" not in dockerfile:
        print(f"missing Dockerfile target: {t}", file=sys.stderr)
        sys.exit(1)
print(f"OK — {len(apps)} supervisor apps match Dockerfile")
PY
