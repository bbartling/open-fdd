#!/usr/bin/env bash
# Export / restore Arrow/Feather historian artifacts on the host (outside containers).
#
#   ./scripts/openfdd_rust_historian_staging.sh export [dest_dir]
#   ./scripts/openfdd_rust_historian_staging.sh restore [src_dir]
#   ./scripts/openfdd_rust_historian_staging.sh verify
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="$ROOT/workspace"
HIST="$WS/data/historian"
DEFAULT_STAGE="$WS/backups/historian-staging/latest"

cmd="${1:-export}"
SRC_OR_DEST="${2:-$DEFAULT_STAGE}"

manifest_write() {
  local dir="$1"
  mkdir -p "$dir"
  {
    echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "source=$HIST"
    echo "host=$(hostname -s 2>/dev/null || hostname)"
    find "$dir" -type f \( -name '*.arrow' -o -name '*.jsonl' -o -name '*.feather' \) -printf '%P %s\n' 2>/dev/null \
      | sort || true
  } >"$dir/staging-manifest.txt"
}

export_historian() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  if [[ -d "$HIST" ]]; then
    mkdir -p "$dest/historian"
    cp -a "$HIST/." "$dest/historian/"
  fi
  while IFS= read -r -d '' f; do
    rel="${f#$WS/data/}"
    mkdir -p "$dest/data/$(dirname "$rel")"
    cp -a "$f" "$dest/data/$rel"
  done < <(find "$WS/data" -type f \( -name '*.arrow' -o -name '*.feather' \) -print0 2>/dev/null || true)
  manifest_write "$dest"
  jq -nc --arg dir "$dest" --argjson files "$(find "$dest" -type f | wc -l | tr -d ' ')" \
    '{action:"export",dest:$dir,file_count:$files,ok:true}' >"$dest/result.json"
  echo "Historian export OK → $dest ($(find "$dest" -type f | wc -l) files)"
}

restore_historian() {
  local src="$1"
  [[ -d "$src" ]] || { echo "ERROR: staging dir missing: $src" >&2; exit 1; }
  mkdir -p "$HIST"

  restore_via_docker() {
    local container="${OPENFDD_BRIDGE_CONTAINER:-openfdd-bridge}"
    command -v docker >/dev/null 2>&1 || return 1
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$container" || return 1
    if [[ -d "$src/historian" ]]; then
      docker cp "$src/historian/." "${container}:/var/openfdd/workspace/data/historian/" >/dev/null 2>&1 \
        && echo "Restore via docker cp → $container" && return 0
    fi
    return 1
  }

  if ! [[ -w "$HIST" ]]; then
    echo "WARN: historian not writable on host — trying docker cp restore"
    restore_via_docker || echo "WARN: docker restore failed; attempting host copy"
  fi
  if restore_via_docker; then
    :
  else
    if [[ -d "$src/historian" ]]; then
      cp -a "$src/historian/." "$HIST/" 2>/dev/null || {
        echo "WARN: host restore partial — container-owned files need docker cp (start openfdd-bridge)"
      }
    elif [[ -d "$src/data/historian" ]]; then
      cp -a "$src/data/historian/." "$HIST/" 2>/dev/null || true
    fi
  fi
  if [[ -d "$src/data" ]]; then
    while IFS= read -r -d '' f; do
      rel="${f#$src/data/}"
      mkdir -p "$WS/data/$(dirname "$rel")" 2>/dev/null || true
      cp -a "$f" "$WS/data/$rel" 2>/dev/null || true
    done < <(find "$src/data" -type f \( -name '*.arrow' -o -name '*.feather' -o -name '*.jsonl' \) -print0 2>/dev/null || true)
  fi
  manifest_write "$src"
  local jsonl arrow feather
  jsonl="$(find "$HIST" -name 'telemetry_pivot.jsonl' 2>/dev/null | head -1)"
  arrow="$(find "$HIST" -name '*.arrow' 2>/dev/null | head -1)"
  feather="$(find "$WS/data" -name '*.feather' 2>/dev/null | head -1)"
  local jsonl_lines=0
  [[ -f "${jsonl:-}" ]] && jsonl_lines="$(wc -l <"$jsonl" | tr -d ' ')"
  jq -nc \
    --arg src "$src" \
    --arg jsonl "${jsonl:-}" \
    --arg arrow "${arrow:-}" \
    --arg feather "${feather:-}" \
    --argjson jsonl_lines "$jsonl_lines" \
    '{action:"restore",src:$src,telemetry_jsonl:$jsonl,telemetry_arrow:$arrow,feather:$feather,jsonl_lines:$jsonl_lines,ok:true}' \
    >"${src}/restore-result.json"
  echo "Historian restore OK ← $src (jsonl lines=$jsonl_lines)"
}

verify_historian() {
  local jsonl arrow
  jsonl="$(find "$HIST" -name 'telemetry_pivot.jsonl' 2>/dev/null | head -1)"
  arrow="$(find "$HIST" -name '*.arrow' 2>/dev/null | head -1)"
  local lines=0 bytes=0
  [[ -f "${jsonl:-}" ]] && lines="$(wc -l <"$jsonl" | tr -d ' ')"
  [[ -f "${arrow:-}" ]] && bytes="$(wc -c <"$arrow" | tr -d ' ')"
  jq -nc --argjson lines "$lines" --argjson bytes "$bytes" \
    --arg jsonl "${jsonl:-}" --arg arrow "${arrow:-}" \
    '{ok:($lines>0 or $bytes>0),jsonl_lines:$lines,arrow_bytes:$bytes,jsonl_path:$jsonl,arrow_path:$arrow}' \
    | tee "${OPENFDD_HISTORIAN_VERIFY_JSON:-/dev/stdout}"
  [[ "$lines" -gt 0 || "$bytes" -gt 0 ]]
}

case "$cmd" in
  export) export_historian "$SRC_OR_DEST" ;;
  restore) restore_historian "$SRC_OR_DEST" ;;
  verify) verify_historian ;;
  *) echo "Usage: $0 export|restore|verify [dir]" >&2; exit 1 ;;
esac
