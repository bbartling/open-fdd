#!/usr/bin/env bash
# Fail if any Content-Security-Policy in frontend/web/nginx.conf allows
# 'unsafe-inline' outside style-src-attr (#1130).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NGINX_CONF="${ROOT}/frontend/web/nginx.conf"

self_test() {
  local fail=0
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<'EOF'
add_header Content-Security-Policy "style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'" always;
EOF
  if CSP_CHECK_FILE="$tmp" python3 - <<'PY'
import os, re, sys
path = os.environ["CSP_CHECK_FILE"]
text = open(path).read()
for line in text.splitlines():
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', line)
    if not m:
        continue
    csp = m.group(1)
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) < 2:
            continue
        directive, *sources = tokens
        if "'unsafe-inline'" in sources and directive != "style-src-attr":
            sys.exit(1)
sys.exit(0)
PY
  then
    echo "OK positive: style-src-attr unsafe-inline allowed"
  else
    echo "FAIL: positive fixture rejected" >&2
    fail=1
  fi

  cat >"$tmp" <<'EOF'
add_header Content-Security-Policy "style-src 'self' 'unsafe-inline'" always;
EOF
  if CSP_CHECK_FILE="$tmp" python3 - <<'PY'
import os, re, sys
path = os.environ["CSP_CHECK_FILE"]
text = open(path).read()
for line in text.splitlines():
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', line)
    if not m:
        continue
    csp = m.group(1)
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) < 2:
            continue
        directive, *sources = tokens
        if "'unsafe-inline'" in sources and directive != "style-src-attr":
            sys.exit(1)
sys.exit(0)
PY
  then
    echo "FAIL: negative fixture accepted" >&2
    fail=1
  else
    echo "OK negative: style-src unsafe-inline rejected"
  fi

  rm -f "$tmp"
  if [[ "$fail" -ne 0 ]]; then
    echo "check_csp_headers.sh --self-test FAILED" >&2
    return 1
  fi
  echo "check_csp_headers.sh --self-test OK"
}

check_nginx() {
  if [[ ! -f "$NGINX_CONF" ]]; then
    echo "FAIL: missing $NGINX_CONF" >&2
    return 1
  fi
  CSP_CHECK_FILE="$NGINX_CONF" python3 - <<'PY'
import os, re, sys

path = os.environ["CSP_CHECK_FILE"]
lines = open(path, encoding="utf-8").read().splitlines()
csps = []
for i, line in enumerate(lines, start=1):
    if "Content-Security-Policy" not in line:
        continue
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', line)
    if not m:
        print(f"FAIL: unparseable CSP at {path}:{i}", file=sys.stderr)
        sys.exit(1)
    csps.append((i, m.group(1)))

if not csps:
    print(f"FAIL: no CSP headers in {path}", file=sys.stderr)
    sys.exit(1)

required = {
    "style-src": ["'self'"],
    "style-src-elem": ["'self'"],
    "style-src-attr": ["'unsafe-inline'"],
}

errors = []
for lineno, csp in csps:
    directives = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) < 1:
            continue
        directives[tokens[0]] = tokens[1:]

    for name, want in required.items():
        got = directives.get(name)
        if got != want:
            errors.append(
                f"{path}:{lineno} {name} expected {want!r} got {got!r}"
            )

    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) < 2:
            continue
        directive, *sources = tokens
        if "'unsafe-inline'" in sources and directive != "style-src-attr":
            errors.append(
                f"{path}:{lineno} '{directive}' must not include unsafe-inline"
            )

if errors:
    for err in errors:
        print(f"FAIL: {err}", file=sys.stderr)
    sys.exit(1)

print(f"check_csp_headers: OK ({len(csps)} CSP header(s) in nginx.conf)")
PY
}

usage() {
  echo "Usage: $0 [--self-test]" >&2
}

case "${1:-}" in
  --self-test)
    self_test
    ;;
  ""|-h|--help)
    check_nginx
    ;;
  *)
    usage
    exit 2
    ;;
esac
