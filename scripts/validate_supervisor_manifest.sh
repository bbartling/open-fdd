#!/usr/bin/env bash
# Sanity-check supervisor/manifest.yaml vs docker/Dockerfile targets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = (root / "supervisor/manifest.yaml").read_text()
dockerfile = (root / "docker/Dockerfile").read_text()

# Quoted or bare build_target values (hyphens allowed, e.g. bacnet-poll, mcp-rag)
apps = re.findall(
    r'build_target:\s*(?:"([^"]+)"|\'([^\']+)\'|([\w][\w.-]*))',
    manifest,
)
targets = [a or b or c for a, b, c in apps]

stages = {
    m.group(1)
    for m in re.finditer(
        r"^\s*FROM\s+.+?\s+AS\s+([\w][\w.-]*)\s*$",
        dockerfile,
        re.MULTILINE | re.IGNORECASE,
    )
}

missing = [t for t in targets if t not in stages]
if missing:
    print(f"manifest build_target not in Dockerfile stages: {missing}", file=sys.stderr)
    print(f"Dockerfile stages: {sorted(stages)}", file=sys.stderr)
    sys.exit(1)
print(f"OK — {len(targets)} supervisor apps match Dockerfile")
PY
