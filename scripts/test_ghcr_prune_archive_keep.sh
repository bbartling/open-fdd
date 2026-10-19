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

# The committed pin's index digest must keep an otherwise-deletable old version.
PIN_DIGEST="$(python3 -c 'import json; print(json.load(open("archive/ot-edge/unqualified-cdaa4f15/evidence/oci-pin.json"))["images"][0]["index_digest"])')"
PLATFORM_DIGEST="$(python3 -c 'import json; print(json.load(open("archive/ot-edge/unqualified-cdaa4f15/evidence/oci-pin.json"))["images"][0]["platforms"][0]["digest"])')"
PIN_FIXTURE="$(mktemp)"
python3 - "$PIN_FIXTURE" "$PIN_DIGEST" "$PLATFORM_DIGEST" <<'PY'
import json, sys
path, digest, platform = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump([
    {
        "package": "openfdd-fieldbus",
        "id": "pinned-index",
        "updated_at": "2020-01-01T00:00:00Z",
        "digest": digest,
        "tags": ["sha-oldpin", "3.6.1"],
    },
    {
        "package": "openfdd-fieldbus",
        "id": "pinned-platform",
        "updated_at": "2020-01-01T00:00:00Z",
        "digest": platform,
        "tags": [],
    },
], open(path, "w"))
PY
PIN_OUT="$(mktemp)"
./scripts/ghcr_prune_packages.sh \
  --package openfdd-fieldbus \
  --fixture "$PIN_FIXTURE" \
  --keep-releases 0 \
  --delete-sha-older-than-days 7 \
  --delete-untagged-older-than-days 7 \
  --dry-run \
  --json-out "$PIN_OUT" >/dev/null
python3 - "$PIN_OUT" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
by = {row["id"]: row for row in plan}
for key in ("pinned-index", "pinned-platform"):
    row = by[key]
    assert row["action"] == "keep" and row["reason"] == "archive-digest", row
print("OK ghcr prune keeps the committed OT index and platform digests")
PY
rm -f "$PIN_FIXTURE" "$PIN_OUT"
