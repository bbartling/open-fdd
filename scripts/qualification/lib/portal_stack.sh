# shellcheck shell=bash
# Disposable portal stack helpers (deployment profile `cloud_portal`).
#
# Source from a recipe after setting ROOT. Call portal_stack_init <kind>, then
# portal_stack_up. Install `trap portal_stack_cleanup EXIT` right after init.
#
# Secrets (JWT secret, admin + Timescale passwords, user passwords) are
# generated per run, written only to a 0600 env file under a 0700 private dir,
# and passed to curl through header/body files or stdin — never argv or logs.
# Teardown removes only this run's compose project and the volumes labelled
# with that project. It never calls `down -v` and never prunes.

PORTAL_QUAL_COMPOSE_MIN="2.24.4"
PORTAL_ALPINE_IMAGE="${OPENFDD_QUAL_ALPINE_IMAGE:-alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc}"
PORTAL_COMPOSE_PROFILES=()
PORTAL_QUAL_SECRET_VARS=(
  OPENFDD_JWT_SECRET OPENFDD_ADMIN_PASSWORD OPENFDD_AGENT_PASSWORD
  OPENFDD_TIMESCALE_PASSWORD OPENFDD_DATABASE_URL OPENFDD_PROVIDER_SITES
  NF_CLIENT_ID NF_CLIENT_SECRET OPENFDD_ALLOW_OPEN_BIND
)

portal_die() {
  echo "FAIL: $*" >&2
  exit 1
}

portal_require_tag() {
  PORTAL_TAG="${OPENFDD_IMAGE_TAG:?set OPENFDD_IMAGE_TAG to an immutable sha-<7> tag}"
  if [[ ! "$PORTAL_TAG" =~ ^sha-[0-9a-f]{7}$ ]]; then
    portal_die "OPENFDD_IMAGE_TAG must match sha-<7 lowercase hex>, got: $PORTAL_TAG"
  fi
}

portal_version_ge() {
  # portal_version_ge <have> <want>
  [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

portal_preflight() {
  local cmd have
  for cmd in docker curl jq python3; do
    command -v "$cmd" >/dev/null || portal_die "missing required command: $cmd"
  done
  docker info >/dev/null 2>&1 || portal_die "docker daemon unavailable"
  have="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
  [[ -n "$have" ]] || portal_die "docker compose v2 plugin required"
  portal_version_ge "$have" "$PORTAL_QUAL_COMPOSE_MIN" \
    || portal_die "docker compose >= $PORTAL_QUAL_COMPOSE_MIN required (have $have)"
}

portal_py() {
  python3 -B "$ROOT/scripts/qualification/portal/portal_qual.py" "$@"
}

portal_free_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

# portal_stack_init <kind> — sets PORTAL_PREFIX PORTAL_PROJECT PORTAL_PRIV
# PORTAL_PLAN PORTAL_WEB_PORT PORTAL_BASE PORTAL_STEPS. Requires ART.
portal_stack_init() {
  local kind="$1" jwt admin_pw ts_pw
  [[ -n "${ART:-}" ]] || portal_die "ART must be set before portal_stack_init"
  local var
  for var in "${PORTAL_QUAL_SECRET_VARS[@]}"; do
    unset "$var"
  done
  PORTAL_PREFIX="$(portal_py prefix)"
  PORTAL_PROJECT="$(portal_py project --kind "$kind" --prefix "$PORTAL_PREFIX")"
  PORTAL_PRIV="$(mktemp -d "${TMPDIR:-/tmp}/openfdd-qual-priv.XXXXXX")"
  chmod 700 "$PORTAL_PRIV"
  PORTAL_PLAN="$ART/plan.json"
  PORTAL_STEPS="$ART/steps.jsonl"
  : >"$PORTAL_STEPS"
  portal_py plan --prefix "$PORTAL_PREFIX" >"$PORTAL_PLAN"
  PORTAL_WEB_PORT="$(portal_free_port)"
  PORTAL_BASE="http://127.0.0.1:${PORTAL_WEB_PORT}"

  jwt="$(portal_py secret --bytes 48)"
  admin_pw="$(portal_py secret --bytes 32)"
  ts_pw="$(portal_py secret --bytes 32)"
  (( ${#jwt} >= 48 )) || portal_die "generated JWT secret too short"
  umask 077
  {
    printf "OPENFDD_IMAGE_TAG='%s'\n" "$PORTAL_TAG"
    printf "PORTAL_QUAL_WEB_PORT='%s'\n" "$PORTAL_WEB_PORT"
    printf "OPENFDD_JWT_SECRET='%s'\n" "$jwt"
    printf "OPENFDD_ADMIN_PASSWORD='%s'\n" "$admin_pw"
    printf "OPENFDD_TIMESCALE_PASSWORD='%s'\n" "$ts_pw"
    printf "OPENFDD_DATABASE_URL='postgresql://openfdd:%s@timescale:5432/openfdd'\n" "$ts_pw"
    printf "OPENFDD_LOG_FORMAT='json'\n"
  } >"$PORTAL_PRIV/stack.env"
  printf '%s' "$admin_pw" >"$PORTAL_PRIV/pw.admin"
  printf '%s' "$jwt" >"$PORTAL_PRIV/jwt.secret"
  printf '%s' "$ts_pw" >"$PORTAL_PRIV/pw.timescale"
  umask 022
  jq -n --arg project "$PORTAL_PROJECT" --arg prefix "$PORTAL_PREFIX" \
    --arg tag "$PORTAL_TAG" --arg base "$PORTAL_BASE" \
    '{project: $project, prefix: $prefix, image_tag: $tag, base_url: $base,
      jwt_secret_chars: "redacted (>=48)", secrets: "private env file, removed on exit"}' \
    >"$ART/run.json"
}

# Adds the NF emulator provider config to the private env file.
portal_enable_nf() {
  local sites
  sites="$(portal_py provider-sites --plan "$PORTAL_PLAN")"
  printf "OPENFDD_PROVIDER_SITES='%s'\nOPENFDD_PROVIDER_POLL='1'\n" "$sites" >>"$PORTAL_PRIV/stack.env"
  PORTAL_COMPOSE_PROFILES=(--profile nf)
}

portal_compose() {
  docker compose -p "$PORTAL_PROJECT" --env-file "$PORTAL_PRIV/stack.env" \
    "${PORTAL_COMPOSE_PROFILES[@]}" \
    -f "$ROOT/docker/compose.portal.yml" \
    -f "$ROOT/docker/compose.timescale.yml" \
    -f "$ROOT/docker/compose.portal-qual.yml" \
    "$@"
}

portal_stack_pull() {
  local svc=(central web timescale)
  [[ ${#PORTAL_COMPOSE_PROFILES[@]} -gt 0 ]] && svc+=(nf-emulator)
  portal_compose pull --quiet "${svc[@]}" >/dev/null
}

portal_wait_health() {
  local deadline=$((SECONDS + ${1:-180}))
  until curl -fsS --max-time 5 "$PORTAL_BASE/api/health" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      portal_compose ps >&2 || true
      portal_compose logs --no-color --tail 80 central web >&2 || true
      portal_die "portal stack never became healthy at $PORTAL_BASE"
    fi
    sleep 2
  done
}

portal_stack_up() {
  portal_stack_pull
  portal_compose up -d --no-build --quiet-pull >/dev/null
  portal_wait_health "${1:-180}"
}

portal_project_volumes() {
  docker volume ls -q --filter "label=com.docker.compose.project=${PORTAL_PROJECT}"
}

# portal_volume_name <compose volume key> → this project's docker volume name.
portal_volume_name() {
  printf '%s_%s' "$PORTAL_PROJECT" "$1"
}

portal_project_guard() {
  [[ -n "${PORTAL_PROJECT:-}" && "$PORTAL_PROJECT" =~ ^openfdd-qual-[a-z0-9-]+$ ]]
}

# Stops this project and removes only volumes labelled with this project and
# named with its prefix. Never `down -v`, never prune.
portal_remove_project_volumes() {
  local vol
  portal_project_guard || portal_die "refusing volume removal outside an openfdd-qual-* project"
  portal_compose down --remove-orphans --timeout 10 >/dev/null 2>&1 || true
  while read -r vol; do
    [[ -n "$vol" && "$vol" == "${PORTAL_PROJECT}_"* ]] || continue
    docker volume rm "$vol" >/dev/null 2>&1 || true
  done < <(portal_project_volumes 2>/dev/null)
}

# portal_volume_run <volume> <mode ro|rw> <cmd...> — pinned alpine with the
# volume at /w (runs as root so it can read the service-owned files).
portal_volume_run() {
  local vol="$1" mode="$2"
  shift 2
  docker run --rm -i --network none -v "${vol}:/w:${mode}" "$PORTAL_ALPINE_IMAGE" "$@"
}

# Project-scoped teardown: this project's containers, networks, and labelled
# volumes only.
portal_stack_cleanup() {
  local rc=$?
  if portal_project_guard; then
    if [[ -n "${ART:-}" && -d "$ART" && "${PORTAL_KEEP_LOGS:-1}" == "1" ]]; then
      portal_compose logs --no-color --timestamps >"$ART/compose.log" 2>&1 || true
      portal_redact_file "$ART/compose.log"
    fi
    portal_remove_project_volumes
  fi
  if [[ -n "${PORTAL_PRIV:-}" && -d "$PORTAL_PRIV" ]]; then
    rm -rf "$PORTAL_PRIV"
  fi
  return "$rc"
}

# Removes every generated secret value from a log artifact in place.
portal_redact_file() {
  local file="$1"
  [[ -f "$file" && -d "${PORTAL_PRIV:-}" ]] || return 0
  python3 - "$file" "$PORTAL_PRIV" <<'PY'
import sys
from pathlib import Path
target, priv = Path(sys.argv[1]), Path(sys.argv[2])
secrets = set()
for p in priv.iterdir():
    if p.is_file() and (p.name.startswith("pw.") or p.name == "jwt.secret" or p.name.startswith("tok.")):
        v = p.read_text(encoding="utf-8").strip()
        if len(v) >= 16:
            secrets.add(v)
try:
    text = target.read_text(encoding="utf-8", errors="replace")
except OSError:
    try:
        target.unlink()
    except OSError:
        pass
    print(f"redact: removed unreadable artifact: {target}", file=sys.stderr)
    sys.exit(0)
redacted = text
for v in sorted(secrets, key=len, reverse=True):
    redacted = redacted.replace(v, "[REDACTED]")
if redacted != text:
    try:
        target.write_text(redacted, encoding="utf-8")
    except OSError:
        target.unlink(missing_ok=True)
        print(f"redact: removed unwritable artifact with secrets: {target}", file=sys.stderr)
PY
}

# portal_step <id> <PASS|FAIL|BLOCKED|...> [detail]
portal_step() {
  jq -cn --arg id "$1" --arg status "$2" --arg detail "${3:-}" \
    '{id: $id, status: $status, detail: ($detail | select(length > 0))}' >>"$PORTAL_STEPS"
  echo "[$2] $1${3:+ — $3}"
}

# portal_api <identity|-> <METHOD> <PATH> [body-file|-] [content-type]
# Writes the body to stdout and the HTTP status to a private file, so callers
# may run it in $(...) or a pipeline and still read portal_last_status.
portal_api() {
  local ident="$1" method="$2" path="$3" body="${4:-}" ctype="${5:-application/json}"
  local out="$PORTAL_PRIV/resp.$$"
  local args=(-sS --max-time 30 -o "$out" -w '%{http_code}' -X "$method")
  if [[ "$ident" != "-" ]]; then
    args+=(-H "@$PORTAL_PRIV/hdr.$ident")
  fi
  if [[ -n "$body" ]]; then
    args+=(-H "Content-Type: $ctype" --data-binary "@$body")
  fi
  curl "${args[@]}" "$PORTAL_BASE$path" >"$PORTAL_PRIV/last_status" 2>/dev/null \
    || echo 000 >"$PORTAL_PRIV/last_status"
  cat "$out" 2>/dev/null || true
  rm -f "$out"
}

portal_last_status() {
  cat "$PORTAL_PRIV/last_status" 2>/dev/null || echo 000
}

# portal_login <identity> <username> — password read from $PORTAL_PRIV/pw.<identity>.
portal_login() {
  local ident="$1" user="$2" token
  python3 - "$user" "$PORTAL_PRIV/pw.$ident" >"$PORTAL_PRIV/login.$ident.json" <<'PY'
import json, sys
from pathlib import Path
print(json.dumps({"username": sys.argv[1], "password": Path(sys.argv[2]).read_text(encoding="utf-8")}))
PY
  token="$(portal_api - POST /api/auth/login "$PORTAL_PRIV/login.$ident.json" | jq -r '.token // .access_token // empty')"
  rm -f "$PORTAL_PRIV/login.$ident.json"
  [[ "$(portal_last_status)" == "200" && -n "$token" ]] || return 1
  umask 077
  printf 'Authorization: Bearer %s\n' "$token" >"$PORTAL_PRIV/hdr.$ident"
  printf '%s' "$token" >"$PORTAL_PRIV/tok.$ident"
  umask 022
}

# portal_psql <sql> — tuples-only, unaligned, fail on error.
portal_psql() {
  portal_compose exec -T timescale \
    psql -U openfdd -d "${PORTAL_PSQL_DB:-openfdd}" -At -v ON_ERROR_STOP=1 -c "$1"
}

# Waits for the real Timescale server; the entrypoint's init-time server only
# listens on the unix socket, so probe TCP 127.0.0.1 inside the container.
portal_wait_timescale() {
  local deadline=$((SECONDS + ${1:-120}))
  until portal_compose exec -T timescale pg_isready -q -h 127.0.0.1 -U openfdd -d openfdd >/dev/null 2>&1 \
      && portal_psql "SELECT 1" >/dev/null 2>&1; do
    (( SECONDS >= deadline )) && portal_die "timescale never became ready"
    sleep 2
  done
}

# Row count + md5 over a site's samples in a stable order.
portal_site_fingerprint() {
  local site="$1"
  [[ "$site" =~ ^[A-Za-z0-9_]+$ ]] || portal_die "bad site id $site"
  portal_psql "SELECT count(*) || ':' || coalesce(md5(string_agg(
      openfdd_key || '|' || to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '|' ||
      coalesce(val::text, 'null') || '|' || coalesce(unit, '') || '|' || coalesce(quality, ''),
      E'\\n' ORDER BY openfdd_key, ts)), 'empty')
    FROM sample WHERE site_id = '${site}'"
}

portal_site_count() {
  portal_site_fingerprint "$1" | cut -d: -f1
}

# portal_wait_rows <site> <seconds>
portal_wait_rows() {
  local site="$1" deadline=$((SECONDS + ${2:-120})) n
  while :; do
    n="$(portal_site_count "$site" 2>/dev/null || echo 0)"
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    (( n > 0 )) && { echo "$n"; return 0; }
    (( SECONDS >= deadline )) && { echo 0; return 1; }
    sleep 3
  done
}

portal_image_digest() {
  docker image inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$1" 2>/dev/null || true
}
