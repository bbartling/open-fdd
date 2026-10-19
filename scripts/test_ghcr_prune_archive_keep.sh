#!/usr/bin/env bash
# Dry-run: an archived digest or ot-archive-* tag keeps the whole GHCR version.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
./scripts/ghcr_prune_packages.sh \
  --package openfdd-fieldbus \
  --fixture scripts/fixtures/ghcr_prune_archive_versions.json \
  --protected-digests-file scripts/fixtures/ghcr-archive-protected-digests.fixture.txt \
  --keep-releases 2 \
  --delete-sha-older-than-days 7 \
  --delete-untagged-older-than-days 7 \
  --dry-run \
  --json-out "$OUT" >/dev/null
python3 - "$OUT" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
by = {str(row["id"]): row for row in plan}
assert by["archive-mix"]["action"] == "keep", by["archive-mix"]
assert by["digest-keep"]["action"] == "keep", by["digest-keep"]
assert by["digest-keep"]["reason"] == "archive-digest", by["digest-keep"]
assert by["old-delete"]["action"] == "delete", by["old-delete"]
assert by["sha-only"]["action"] == "delete", by["sha-only"]
print("OK ghcr prune keeps archive tag and digest")
PY
