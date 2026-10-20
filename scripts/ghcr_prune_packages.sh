# Prune old GHCR container package versions (stack + MCP).
set -euo pipefail

OWNER="${GHCR_OWNER:-bbartling}"
KEEP_RELEASES=2
DELETE_UNTAGGED_DAYS=7
DELETE_SHA_DAYS=7
DRY_RUN=1
ALL_IMAGES=0
PROTECTED_FILE=""
PROTECTED_DIGESTS_FILE=""
FIXTURE=""
CURRENT_ACME_TAG=""
PREVIOUS_ACME_TAG=""
JSON_OUT=""
MARKDOWN_OUT=""
PACKAGES=()
PROTECT_TAGS=()
PROTECT_DIGESTS=()

usage() {
  cat <<'EOF'
Usage: ghcr_prune_packages.sh [options]

  --all-images / --package NAME
  --keep-releases N              (default 2 — beta retention)
  --delete-untagged-older-than-days N
  --delete-sha-older-than-days N
  --protected-tags-file PATH
  --protected-digests-file PATH
  --protect-tag TAG
  --fixture PATH                 JSON versions; no gh API call
  --current-acme-tag / --previous-acme-tag
  --dry-run (default) / --confirm-delete
  --json-out PATH / --markdown-out PATH
EOF
}

log() { printf '%s\n' "$*" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all-images) ALL_IMAGES=1; shift ;;
    --package) PACKAGES+=("$2"); shift 2 ;;
    --keep-releases) KEEP_RELEASES="$2"; shift 2 ;;
    --delete-untagged-older-than-days) DELETE_UNTAGGED_DAYS="$2"; shift 2 ;;
    --delete-sha-older-than-days) DELETE_SHA_DAYS="$2"; shift 2 ;;
    --protected-tags-file) PROTECTED_FILE="$2"; shift 2 ;;
    --protected-digests-file) PROTECTED_DIGESTS_FILE="$2"; shift 2 ;;
    --protect-tag) PROTECT_TAGS+=("$2"); shift 2 ;;
    --fixture) FIXTURE="$2"; shift 2 ;;
    --current-acme-tag) CURRENT_ACME_TAG="$2"; shift 2 ;;
    --previous-acme-tag) PREVIOUS_ACME_TAG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --confirm-delete) DRY_RUN=0; shift ;;
    --json-out) JSON_OUT="$2"; shift 2 ;;
    --markdown-out) MARKDOWN_OUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log "Unknown option: $1"; usage; exit 2 ;;
  esac
done

[[ "$ALL_IMAGES" -eq 1 ]] && PACKAGES=(openfdd-central openfdd-web openfdd-fieldbus openfdd-mqtt openfdd-mcp)
[[ ${#PACKAGES[@]} -eq 0 ]] && PACKAGES=(openfdd-central openfdd-web openfdd-fieldbus openfdd-mqtt openfdd-mcp)

load_protected() {
  if [[ -n "$PROTECTED_FILE" && -f "$PROTECTED_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      line="$(echo "$line" | tr -d '[:space:]')"
      [[ -n "$line" ]] && PROTECT_TAGS+=("$line")
    done <"$PROTECTED_FILE"
  fi
  if [[ -n "$PROTECTED_DIGESTS_FILE" && -f "$PROTECTED_DIGESTS_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      line="$(echo "$line" | tr -d '[:space:]')"
      [[ -n "$line" ]] && PROTECT_DIGESTS+=("$line")
    done <"$PROTECTED_DIGESTS_FILE"
  fi
  local default_digests
  default_digests="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ghcr-archive-protected-digests.txt"
  if [[ -z "$PROTECTED_DIGESTS_FILE" && -f "$default_digests" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      line="$(echo "$line" | tr -d '[:space:]')"
      [[ -n "$line" ]] && PROTECT_DIGESTS+=("$line")
    done <"$default_digests"
  fi
  [[ -n "$CURRENT_ACME_TAG" ]] && PROTECT_TAGS+=("$CURRENT_ACME_TAG" "v${CURRENT_ACME_TAG}")
  [[ -n "$PREVIOUS_ACME_TAG" ]] && PROTECT_TAGS+=("$PREVIOUS_ACME_TAG" "v${PREVIOUS_ACME_TAG}")
  if [[ -f VERSION ]]; then
    local ver
    ver="$(tr -d '[:space:]' <VERSION)"
    [[ -n "$ver" ]] && PROTECT_TAGS+=("$ver" "v$ver")
  fi
}

is_archive_tag() {
  local tag="$1"
  [[ "$tag" == ot-archive-* ]] && return 0
  [[ "$tag" == ot-mqtt-fieldbus-last-good-* ]] && return 0
  return 1
}

is_protected_tag() {
  local tag="$1" t
  is_archive_tag "$tag" && return 0
  for t in "${PROTECT_TAGS[@]}"; do
    [[ "$tag" == "$t" ]] && return 0
  done
  return 1
}

is_protected_digest() {
  local digest="$1" d
  [[ -z "$digest" || "$digest" == "null" ]] && return 1
  for d in "${PROTECT_DIGESTS[@]}"; do
    [[ "$digest" == "$d" ]] && return 0
  done
  return 1
}

semver_key() {
  local tag="${1#v}"
  if [[ "$tag" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    printf '%04d.%04d.%04d|%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "$tag"
  fi
}

version_age_days() {
  local updated="$1" epoch now
  now="$(date -u +%s)"
  epoch="$(date -u -d "$updated" +%s 2>/dev/null || echo 0)"
  echo $(( (now - epoch) / 86400 ))
}

list_versions() {
  local pkg="$1"
  gh api "/users/${OWNER}/packages/container/${pkg}/versions?per_page=100" --paginate \
    --jq '.[] | {id, updated_at, digest: (.name // ""), tags: (.metadata.container.tags // [])}'
}

decide_action() {
  local tags_json="$1" updated="$2" digest="${3:-}"
  local age action reason
  age="$(version_age_days "$updated")"
  action="keep"
  reason="default"

  # Digest protection wins over age, including untagged platform manifests.
  if is_protected_digest "$digest"; then
    echo "keep|archive-digest"
    return
  fi

  local tag_count
  tag_count="$(echo "$tags_json" | jq 'length')"

  if [[ "$tag_count" -eq 0 ]]; then
    if [[ "$age" -ge "$DELETE_UNTAGGED_DAYS" ]]; then
      echo "delete|untagged-old"
    else
      echo "keep|untagged-recent"
    fi
    return
  fi

  local has_protected=0 has_semver_old=0 has_sha_old=0 has_semver_keep=0
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    if is_protected_tag "$tag"; then
      has_protected=1
    fi
    if [[ "$tag" == sha-* && "$age" -ge "$DELETE_SHA_DAYS" ]]; then
      has_sha_old=1
    fi
    local key="$(semver_key "$tag" || true)"
    if [[ -n "$key" ]]; then
      local norm="${key#*|}"
      if [[ " ${SEMVER_KEEP[*]} " == *" $norm "* || " ${SEMVER_KEEP[*]} " == *" v$norm "* ]]; then
        has_semver_keep=1
      else
        has_semver_old=1
      fi
    fi
  done < <(echo "$tags_json" | jq -r '.[]')

  if [[ "$has_protected" -eq 1 || "$has_semver_keep" -eq 1 ]]; then
    echo "keep|protected-or-recent-release"
    return
  fi
  if [[ "$has_sha_old" -eq 1 && "$has_semver_old" -eq 0 ]]; then
    echo "delete|sha-old"
    return
  fi
  if [[ "$has_semver_old" -eq 1 ]]; then
    echo "delete|semver-outside-keep-window"
    return
  fi
  echo "keep|recent"
}

load_protected
PLAN_JSON="[]"

if [[ -n "$FIXTURE" ]]; then
  versions_by_pkg="$(jq -c '.' "$FIXTURE")"
else
  versions_by_pkg=""
fi

for pkg in "${PACKAGES[@]}"; do
  log "==> ${OWNER}/${pkg}"
  if [[ -n "$FIXTURE" ]]; then
    versions_json="$(echo "$versions_by_pkg" | jq -c --arg pkg "$pkg" '[.[] | select(.package == $pkg)]')"
  else
    versions_json="$(list_versions "$pkg" | jq -s '.')" || {
      log "    skip (gh api failed — need read:packages)"
      continue
    }
  fi

  mapfile -t SEMVER_KEEP < <(
    echo "$versions_json" | jq -r '.[].tags[]?' | sort -u | while read -r tag; do
      key="$(semver_key "$tag" || true)"
      [[ -n "$key" ]] && echo "$key"
    done | sort -r | head -n "$KEEP_RELEASES" | cut -d'|' -f2
  )

  log "    keeping semver tags: ${SEMVER_KEEP[*]:-none}"

  while IFS= read -r row; do
    vid="$(echo "$row" | jq -r '.id')"
    updated="$(echo "$row" | jq -r '.updated_at')"
    digest="$(echo "$row" | jq -r '.digest // empty')"
    tags="$(echo "$row" | jq -c '.tags')"
    IFS='|' read -r action reason < <(decide_action "$tags" "$updated" "$digest")
    log "    ${action^^} id=${vid} (${reason}) tags=${tags}"
    PLAN_JSON="$(jq -nc --argjson arr "$PLAN_JSON" \
      --arg pkg "$pkg" --arg id "$vid" --arg action "$action" --arg reason "$reason" --argjson tags "$tags" \
      '$arr + [{package:$pkg, id:$id, action:$action, reason:$reason, tags:$tags}]')"
    if [[ "$action" == "delete" && "$DRY_RUN" -eq 0 ]]; then
      gh api -X DELETE "/users/${OWNER}/packages/container/${pkg}/versions/${vid}" >/dev/null
    fi
  done < <(echo "$versions_json" | jq -c '.[]')
done

[[ -n "$JSON_OUT" ]] && echo "$PLAN_JSON" | jq '.' >"$JSON_OUT"
[[ -n "$MARKDOWN_OUT" ]] && echo "$PLAN_JSON" | jq -r '"# GHCR prune plan\n\n" + (map("| \(.package) | \(.id) | \(.action) | \(.reason) |") | join("\n"))' >"$MARKDOWN_OUT"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "Dry run — pass --confirm-delete to delete."
else
  log "Done."
fi
