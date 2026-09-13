#!/usr/bin/env bash
# Run OUTSIDE Cursor agent (your Mint terminal). Writes a status file the agent can read.
# Usage: ./scripts/ops/wave_n_auth_validate_host.sh
set -euo pipefail
OUT="${1:-/home/ben/Desktop/open-fdd/reports/wave_n_auth_host_status.json}"
mkdir -p "$(dirname "$OUT")"

GH_OK=false
GH_LOGIN=""
RW_OK=false
RW_USER=""
STATUS_OK=false
: >/tmp/wave_n_gh_status.txt
: >/tmp/wave_n_rw_whoami.txt
: >/tmp/wave_n_rw_status.txt

if gh auth status >/tmp/wave_n_gh_status.txt 2>&1; then
  if LOGIN="$(gh api user --jq .login 2>/dev/null)"; then
    GH_OK=true
    GH_LOGIN="$LOGIN"
  fi
fi

if WHO="$(railway whoami 2>/tmp/wave_n_rw_whoami.txt)"; then
  RW_OK=true
  RW_USER="$(echo "$WHO" | tr -d '\n')"
else
  RW_USER="$(tr -d '\n' </tmp/wave_n_rw_whoami.txt | head -c 200)"
fi

if (cd /home/ben/Desktop/open-fdd && railway status >/tmp/wave_n_rw_status.txt 2>&1); then
  STATUS_OK=true
fi

HOSTS="${HOME}/.config/gh/hosts.yml"
HAS_OAUTH=false
if [[ -f "$HOSTS" ]] && grep -q 'oauth_token:' "$HOSTS"; then
  HAS_OAUTH=true
fi

python3 - "$OUT" "$GH_OK" "$GH_LOGIN" "$RW_OK" "$RW_USER" "$STATUS_OK" "$HAS_OAUTH" <<'PY'
import json, pathlib, sys
out, gh_ok, gh_login, rw_ok, rw_user, status_ok, has_oauth = sys.argv[1:8]
def read(p):
  try: return pathlib.Path(p).read_text().strip()
  except Exception: return ""
payload = {
  "ok": gh_ok == "true" and rw_ok == "true",
  "gh_ok": gh_ok == "true",
  "gh_login": gh_login,
  "railway_ok": rw_ok == "true",
  "railway_whoami": rw_user,
  "railway_status_ok": status_ok == "true",
  "railway_status_head": "\n".join(read("/tmp/wave_n_rw_status.txt").splitlines()[:20]),
  "gh_status_head": "\n".join(read("/tmp/wave_n_gh_status.txt").splitlines()[:20]),
  "hosts_yml_has_oauth_token": has_oauth == "true",
}
pathlib.Path(out).write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
print(f"wrote {out}")
PY
