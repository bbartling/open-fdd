#!/usr/bin/env bash
# Resolve site_id + edge_id for gate 35 MQTT pause/resume commands.
# Prefer EXPECTED_* over empty edge site / silent lab defaults.
#
# Usage (from gate script):
#   source lib_pick_edge.sh
#   resolve_edge_target "$edges_json"  # echoes "site edge"; returns 0/2
#
# Env:
#   EXPECTED_EDGE_ID / EXPECTED_SITE_ID — fail-closed when set and unresolved
#   OPENFDD_SITE_ID / OPENFDD_EDGE_ID — defaults only when EXPECTED_* unset

resolve_edge_target() {
  local edges_json="${1:-}"
  local site="" edge=""
  local edge_site=""

  if [[ -z "$edges_json" ]]; then
    echo "ERROR: resolve_edge_target: empty edges JSON" >&2
    return 2
  fi

  if [[ -n "${EXPECTED_EDGE_ID:-}" ]]; then
    edge="$EXPECTED_EDGE_ID"
    edge_site="$(echo "$edges_json" | jq -r --arg e "$edge" '
      (.edges // [])[]
      | select(.edge_id == $e)
      | (.site_id // .building_id // .site // empty)
    ' | head -1)"
    if [[ -n "$edge_site" ]]; then
      site="$edge_site"
    elif [[ -n "${EXPECTED_SITE_ID:-}" ]]; then
      site="$EXPECTED_SITE_ID"
    fi
  elif [[ -n "${EXPECTED_SITE_ID:-}" ]]; then
    site="$EXPECTED_SITE_ID"
    edge="$(echo "$edges_json" | jq -r --arg s "$EXPECTED_SITE_ID" '
      (.edges // [])[]
      | select(
          ((.site_id // .building_id // .site // "") == $s)
          and (.has_telemetry == true)
        )
      | .edge_id
    ' | head -1)"
    if [[ -z "$edge" ]]; then
      # Site match without requiring telemetry (status-registered edge).
      edge="$(echo "$edges_json" | jq -r --arg s "$EXPECTED_SITE_ID" '
        (.edges // [])[]
        | select((.site_id // .building_id // .site // "") == $s)
        | .edge_id
      ' | head -1)"
    fi
  else
    site="$(echo "$edges_json" | jq -r '
      (.edges // [])[]
      | select(.has_telemetry == true)
      | (.site_id // .building_id // .site // empty)
    ' | head -1)"
    edge="$(echo "$edges_json" | jq -r '
      (.edges // [])[]
      | select(.has_telemetry == true)
      | .edge_id
    ' | head -1)"
  fi

  # When EXPECTED_SITE_ID is set, prefer it over empty edge site; never invent lab.
  if [[ -n "${EXPECTED_SITE_ID:-}" ]]; then
    if [[ -z "$site" ]]; then
      site="$EXPECTED_SITE_ID"
    elif [[ "$site" != "$EXPECTED_SITE_ID" ]]; then
      echo "ERROR: resolve_edge_target: edge site_id='$site' != EXPECTED_SITE_ID='$EXPECTED_SITE_ID' (refusing wrong building path)" >&2
      return 2
    fi
  fi

  if [[ -n "${EXPECTED_EDGE_ID:-}" || -n "${EXPECTED_SITE_ID:-}" ]]; then
    if [[ -z "$site" || -z "$edge" ]]; then
      echo "ERROR: resolve_edge_target: unresolved site/edge (site='${site:-}' edge='${edge:-}'; EXPECTED_SITE_ID='${EXPECTED_SITE_ID:-}' EXPECTED_EDGE_ID='${EXPECTED_EDGE_ID:-}'). Refusing lab fallback." >&2
      return 2
    fi
    echo "$site" "$edge"
    return 0
  fi

  site="${site:-${OPENFDD_SITE_ID:-lab}}"
  edge="${edge:-${OPENFDD_EDGE_ID:-fieldbus-1}}"
  echo "$site" "$edge"
  return 0
}
