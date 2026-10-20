# Shared data-safety guards for update, bootstrap, and compose helpers.
# Source this file. It does not change shell options and does not delete anything.
#
# Destructive database or volume actions stay off unless the operator opts in:
#   OPENFDD_ALLOW_DESTRUCTIVE_DB=1
#   or both --reset-db and --i-understand-data-loss (callers pass those as 1/0)

openfdd_destructive_db_allowed() {
  local raw="${OPENFDD_ALLOW_DESTRUCTIVE_DB:-}"
  raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  case "$raw" in
    1|true|yes) return 0 ;;
    *) return 1 ;;
  esac
}

# $1 = 1 when --reset-db was passed, $2 = 1 when --i-understand-data-loss was passed.
openfdd_data_loss_opt_in() {
  local reset_db="${1:-0}"
  local understand="${2:-0}"
  if [[ "$reset_db" == "1" && "$understand" == "1" ]]; then
    return 0
  fi
  openfdd_destructive_db_allowed
}

openfdd_is_protected_data_name() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    return 0
  fi
  case "$name" in
    *openfdd-timescale*|*openfdd_timescale*) return 0 ;;
  esac
  return 1
}

# Names created by disposable CI/qualification scripts, not product stacks.
openfdd_is_ephemeral_data_name() {
  local name="${1:-}"
  case "$name" in
    openfdd-csv-smoke-*|openfdd-restore-empty-*|openfdd-bacnet-mqtt-ci-*|openfdd-zap-*)
      return 0
      ;;
  esac
  return 1
}

# Allow deleting one named volume or compose project.
# Product Timescale names always require OPENFDD_ALLOW_DESTRUCTIVE_DB.
# Disposable script names are allowed because those scripts create them.
# Every other name requires the same opt-in.
openfdd_allow_volume_delete() {
  local name="${1:-}"
  if openfdd_is_protected_data_name "$name"; then
    if openfdd_destructive_db_allowed; then
      echo "WARNING: DATA LOSS — deleting protected data name ${name} because OPENFDD_ALLOW_DESTRUCTIVE_DB=1" >&2
      return 0
    fi
    echo "REFUSED: ${name} is a product database or Timescale volume." >&2
    echo "Updates never delete it. Set OPENFDD_ALLOW_DESTRUCTIVE_DB=1 only for an intentional wipe." >&2
    return 1
  fi
  if openfdd_is_ephemeral_data_name "$name"; then
    return 0
  fi
  if openfdd_destructive_db_allowed; then
    echo "WARNING: DATA LOSS — deleting ${name} because OPENFDD_ALLOW_DESTRUCTIVE_DB=1" >&2
    return 0
  fi
  echo "REFUSED: will not delete volume or compose project ${name}." >&2
  echo "Disposable projects must use an openfdd-csv-smoke-*, openfdd-restore-empty-*, openfdd-bacnet-mqtt-ci-*, or openfdd-zap-* name." >&2
  echo "Any other wipe requires OPENFDD_ALLOW_DESTRUCTIVE_DB=1." >&2
  return 1
}

# Refuse compose arguments that drop or recreate volumes unless opt-in is set.
openfdd_reject_destructive_compose_args() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      down|-v|--volumes|--renew-anon-volumes)
        if openfdd_destructive_db_allowed; then
          echo "WARNING: DATA LOSS — compose argument ${arg} allowed because OPENFDD_ALLOW_DESTRUCTIVE_DB=1" >&2
        else
          echo "REFUSED: '${arg}' can drop or recreate database volumes." >&2
          echo "Updates keep named volumes. Set OPENFDD_ALLOW_DESTRUCTIVE_DB=1 to override." >&2
          return 1
        fi
        ;;
    esac
  done
  return 0
}
