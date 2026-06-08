#!/usr/bin/env bash
# Read-only Ubuntu host security posture for Open-FDD edge VMs.
# Run on the edge host (or via SSH). Does not change firewall, packages, or reboot.
#
#   ./scripts/security/check_host_security.sh
#   ./scripts/security/check_host_security.sh --report-dir ./openfdd-security-report
set -euo pipefail

REPORT_DIR="${REPORT_DIR:-openfdd-security-report}"
HOST_REPORT=""

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
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
mkdir -p "$BASE_DIR"
HOST_REPORT="${BASE_DIR}/05-host-security-check.txt"
exec > >(tee -a "$HOST_REPORT") 2>&1

section "Open-FDD host security check — $(date '+%Y-%m-%d %H:%M:%S')"

section "OS identity"
if command -v lsb_release >/dev/null 2>&1; then
  lsb_release -a 2>/dev/null || true
fi
if [[ -f /etc/os-release ]]; then
  grep -E '^(NAME|VERSION|VERSION_ID|PRETTY_NAME)=' /etc/os-release || true
fi

section "Ubuntu EOL / support status"
_eol_warn=0
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  case "${VERSION_ID:-}" in
    16.04|18.04)
      echo "FAIL: Ubuntu ${VERSION_ID} is EOL — rebuild host on 22.04 or 24.04 LTS"
      _eol_warn=1
      ;;
    20.04|22.04|24.04)
      echo "OK: Ubuntu ${VERSION_ID} LTS — supported (keep patched)"
      ;;
    *)
      echo "WARN: Unknown or non-LTS VERSION_ID=${VERSION_ID:-unset} — confirm with IT"
      ;;
  esac
fi
if command -v ubuntu-security-status >/dev/null 2>&1; then
  ubuntu-security-status 2>/dev/null | head -40 || true
elif command -v pro >/dev/null 2>&1; then
  pro status 2>/dev/null | head -20 || true
else
  echo "ubuntu-security-status not installed (sudo apt install ubuntu-advantage-tools)"
fi

section "Pending security updates"
if command -v apt >/dev/null 2>&1; then
  apt list --upgradable 2>/dev/null | head -50 || true
else
  echo "apt not available"
fi

section "Kernel and reboot"
uname -a
if [[ -f /var/run/reboot-required ]]; then
  echo "REBOOT REQUIRED — kernel or libc updates pending"
  cat /var/run/reboot-required.pkgs 2>/dev/null || true
else
  echo "No /var/run/reboot-required flag"
fi

section "Host Python toolchain (Tenable pip/pyOpenSSL)"
if command -v python3 >/dev/null 2>&1; then
  python3 --version
  python3 -m pip show pip setuptools wheel pyOpenSSL cryptography 2>/dev/null \
    | grep -E '^(Name|Version):' || echo "Some packages not installed via pip on host"
  _pyssl="$(python3 -m pip show pyOpenSSL 2>/dev/null | awk '/^Version:/{print $2}')"
  if [[ -n "${_pyssl:-}" ]]; then
    if python3 -c "import sys; v='${_pyssl}'.split('.'); sys.exit(0 if int(v[0])>=26 else 1)" 2>/dev/null; then
      echo "OK: host pyOpenSSL ${_pyssl} >= 26"
    else
      echo "WARN: host pyOpenSSL ${_pyssl} < 26 — upgrade: sudo apt update && sudo apt install --only-upgrade python3-openssl python3-pip || pipx/venv upgrade"
    fi
  fi
else
  echo "python3 not found"
fi

section "OpenSSH (Terrapin / CVE-2023-48795)"
if command -v ssh >/dev/null 2>&1; then
  ssh -V 2>&1 || true
fi
if command -v sshd >/dev/null 2>&1; then
  sshd -T 2>/dev/null | grep -Ei '^(ciphers|macs|kexalgorithms)' || echo "sshd -T requires root"
fi

section "Listening ports (summary)"
if command -v ss >/dev/null 2>&1; then
  ss -tulpn 2>/dev/null | head -60 || true
else
  netstat -tulpn 2>/dev/null | head -60 || true
fi

section "ICMP timestamp (informational)"
echo "Low-severity Nessus finding — block at firewall if IT requires (see docs/security/linux-host-hardening.md)"

section "Done"
echo "Report: ${HOST_REPORT}"
if [[ "$_eol_warn" == "1" ]]; then
  exit 2
fi
