#!/usr/bin/env bash
# Mac/Linux equivalent of Run-OpenFddSecurityScan.ps1
#
#   ./scripts/security/run_openfdd_security_scan.sh
#   ./scripts/security/run_openfdd_security_scan.sh --host 192.168.204.18 --url http://192.168.204.18
#   ./scripts/security/run_openfdd_security_scan.sh --skip-zap
#
# See scripts/security/README.md
set -euo pipefail

HOST_IP="${HOST_IP:-192.168.204.18}"
TARGET_URL="${TARGET_URL:-http://192.168.204.18}"
PORTS="${PORTS:-80,443,8765,8000,8080,5173,8090}"
REPORT_DIR="${REPORT_DIR:-openfdd-security-report}"
SKIP_ZAP=0
SKIP_ZAP_PULL=0
SKIP_NMAP=0
KEEP_EXISTING=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST_IP="$2"; shift 2 ;;
    --url) TARGET_URL="$2"; shift 2 ;;
    --ports) PORTS="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    --skip-zap) SKIP_ZAP=1; shift ;;
    --skip-zap-pull) SKIP_ZAP_PULL=1; shift ;;
    --skip-nmap) SKIP_NMAP=1; shift ;;
    --keep-existing) KEEP_EXISTING=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown: $1" >&2; usage 1 ;;
  esac
done

section() {
  echo ""
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

if [[ "$REPORT_DIR" != /* ]]; then
  BASE_DIR="$(pwd)/${REPORT_DIR}"
else
  BASE_DIR="$REPORT_DIR"
fi

# Only delete the default report folder name under cwd (not arbitrary paths).
_report_leaf="$(basename "$BASE_DIR")"
if [[ -z "$BASE_DIR" || "$BASE_DIR" == "/" || "$BASE_DIR" == "." || "$BASE_DIR" == ".." ]]; then
  echo "Unsafe report directory: $BASE_DIR" >&2
  exit 1
fi
if [[ "$_report_leaf" != "openfdd-security-report" ]]; then
  echo "Report directory must be named openfdd-security-report (got: $_report_leaf)" >&2
  exit 1
fi

if [[ -d "$BASE_DIR" && "$KEEP_EXISTING" == "0" ]]; then
  rm -rf -- "$BASE_DIR"
fi
mkdir -p "$BASE_DIR"

RUN_INFO="${BASE_DIR}/00-run-info.txt"
REACH="${BASE_DIR}/01-web-reachability-and-headers.txt"
WEB_HEADERS="${BASE_DIR}/02-web-response-headers.txt"
WEB_BODY="${BASE_DIR}/03-web-body-sample.html"
NMAP_CONSOLE="${BASE_DIR}/10-nmap-console-output.txt"
NMAP_SERVICES="${BASE_DIR}/11-nmap-openfdd-services.txt"
NMAP_HTTP="${BASE_DIR}/13-nmap-openfdd-http-details.txt"
NMAP_FINDINGS="${BASE_DIR}/30-nmap-findings-summary.txt"
ZAP_CONSOLE="${BASE_DIR}/20-zap-console-output.txt"
ZAP_HTML="21-zap-openfdd-baseline.html"
ZAP_JSON="21-zap-openfdd-baseline.json"
ZAP_MD="21-zap-openfdd-baseline.md"
ZAP_FINDINGS="${BASE_DIR}/31-zap-findings-summary.txt"
QUICK="${BASE_DIR}/90-quick-findings-summary.txt"
CHECKLIST="${BASE_DIR}/99-review-checklist.txt"

section "Open-FDD local security scan"
echo "Report folder: $BASE_DIR"
echo "Host IP:       $HOST_IP"
echo "Target URL:    $TARGET_URL"
echo "Ports:         $PORTS"

cat >"$RUN_INFO" <<EOF
Open-FDD local security scan
Run time:    $(date '+%Y-%m-%d %H:%M:%S')
Host IP:     $HOST_IP
Target URL:  $TARGET_URL
Ports:       $PORTS
Hostname:    $(hostname)

Notes:
- ZAP baseline is passive/baseline web testing.
- Nmap scan is scoped to one host only: $HOST_IP
- This script deletes/recreates the report folder unless --keep-existing is used.
EOF

section "Checking tools"
DOCKER_OK=0
NMAP_OK=0

if command -v docker >/dev/null 2>&1; then
  docker --version >>"$RUN_INFO" 2>&1 || true
  if docker info >/dev/null 2>&1; then
    DOCKER_OK=1
    echo "Docker is available."
    docker info >"${BASE_DIR}/00-docker-info.txt" 2>&1 || true
  else
    echo "Docker exists but docker info failed — is Docker Desktop/daemon running?"
  fi
else
  echo "Docker not found."
fi

if command -v nmap >/dev/null 2>&1; then
  nmap --version >>"$RUN_INFO" 2>&1 || true
  NMAP_OK=1
  echo "Nmap is available."
else
  echo "Nmap not found. macOS: brew install nmap"
fi

section "Testing web target"
TARGET_OK=0
{
  echo "> curl -k -sS -L --max-time 20 -D headers -o body $TARGET_URL"
  echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
} >"$REACH"

if curl -k -sS -L --max-time 20 -D "$WEB_HEADERS" -o "$WEB_BODY" "$TARGET_URL" >>"$REACH" 2>&1; then
  TARGET_OK=1
  echo "Target web URL responded."
else
  echo "Target web URL did not respond cleanly."
fi

{
  echo ""
  echo "=== Response headers ==="
  head -120 "$WEB_HEADERS" 2>/dev/null || true
  echo ""
  echo "=== Body sample first lines ==="
  head -80 "$WEB_BODY" 2>/dev/null || true
} >>"$REACH"

if [[ "$SKIP_ZAP" == "0" ]]; then
  section "Running OWASP ZAP baseline"
  if [[ "$DOCKER_OK" == "0" ]]; then
    echo "SKIPPED: Docker unavailable." >"$ZAP_CONSOLE"
  elif [[ "$TARGET_OK" == "0" ]]; then
    echo "SKIPPED: target not reachable. Use Caddy URL http://$HOST_IP/" >"$ZAP_CONSOLE"
  else
    if [[ "$SKIP_ZAP_PULL" == "0" ]]; then
      docker pull ghcr.io/zaproxy/zaproxy:stable >"$ZAP_CONSOLE" 2>&1 || true
    fi
    {
      echo "Running zap-baseline.py against $TARGET_URL"
      docker run --rm \
        -v "${BASE_DIR}:/zap/wrk/:rw" \
        -t ghcr.io/zaproxy/zaproxy:stable \
        zap-baseline.py \
        -t "$TARGET_URL" \
        -r "$ZAP_HTML" \
        -J "$ZAP_JSON" \
        -w "$ZAP_MD" \
        -I
    } >>"$ZAP_CONSOLE" 2>&1 || true
  fi
else
  echo "SKIPPED by --skip-zap." >"$ZAP_CONSOLE"
fi

if [[ "$SKIP_NMAP" == "0" && "$NMAP_OK" == "1" ]]; then
  section "Running Nmap scans"
  {
    echo "> nmap -Pn -sV -T2 -p $PORTS $HOST_IP"
    nmap -Pn -sV -T2 -p "$PORTS" "$HOST_IP" \
      -oN "$NMAP_SERVICES" \
      -oX "${BASE_DIR}/11-nmap-openfdd-services.xml" \
      -oG "${BASE_DIR}/11-nmap-openfdd-services.gnmap"
    echo ""
    echo "> nmap http-headers scripts"
    nmap -Pn -sV -T2 --script http-title,http-headers,ssl-cert -p "$PORTS" "$HOST_IP" -oN "$NMAP_HTTP"
  } >"$NMAP_CONSOLE" 2>&1 || true
elif [[ "$SKIP_NMAP" == "1" ]]; then
  echo "SKIPPED by --skip-nmap." >"$NMAP_CONSOLE"
else
  echo "SKIPPED: nmap not installed." >"$NMAP_CONSOLE"
fi

section "Writing summaries"
cat >"$NMAP_FINDINGS" <<EOF
Nmap findings summary
Generated: $(date '+%Y-%m-%d %H:%M:%S')
Host: $HOST_IP
Ports checked: $PORTS
EOF
if [[ -f "$NMAP_SERVICES" ]]; then
  echo "" >>"$NMAP_FINDINGS"
  echo "=== Port state lines ===" >>"$NMAP_FINDINGS"
  grep -E '^[0-9]+/tcp' "$NMAP_SERVICES" >>"$NMAP_FINDINGS" 2>/dev/null || true
fi

cat >"$ZAP_FINDINGS" <<EOF
ZAP findings summary
Generated: $(date '+%Y-%m-%d %H:%M:%S')
Target: $TARGET_URL
EOF
if [[ -f "${BASE_DIR}/${ZAP_MD}" ]]; then
  grep -iE 'WARN|FAIL|High|Medium|Low|CSP|X-Frame|Header' "${BASE_DIR}/${ZAP_MD}" 2>/dev/null |
    head -80 >>"$ZAP_FINDINGS" || true
fi

cat >"$QUICK" <<EOF
Open-FDD quick findings summary
Generated: $(date '+%Y-%m-%d %H:%M:%S')
Report folder: $BASE_DIR
Host: $HOST_IP  URL: $TARGET_URL
EOF
if [[ -f "$NMAP_SERVICES" ]]; then
  echo "" >>"$QUICK"
  echo "Nmap ports:" >>"$QUICK"
  grep -E '^[0-9]+/tcp' "$NMAP_SERVICES" >>"$QUICK" 2>/dev/null || true
fi
if [[ -f "${BASE_DIR}/${ZAP_MD}" ]]; then
  echo "" >>"$QUICK"
  echo "ZAP snippets:" >>"$QUICK"
  grep -iE 'WARN|FAIL|High|Medium|Low|CSP|X-Frame|Header' "${BASE_DIR}/${ZAP_MD}" 2>/dev/null |
    head -40 >>"$QUICK" || true
fi

cat >"$CHECKLIST" <<EOF
Open-FDD local security review checklist
Host: $HOST_IP  URL: $TARGET_URL

Read first: 90-quick-findings-summary.txt, 30-nmap-findings-summary.txt, 31-zap-findings-summary.txt
Docs: docs/security/zap-baseline.md, docs/developer/security-testing.md
EOF

section "Done"
echo "Reports saved to: $BASE_DIR"
echo "Read first: $QUICK (if present), $NMAP_FINDINGS, $ZAP_FINDINGS, $CHECKLIST"
