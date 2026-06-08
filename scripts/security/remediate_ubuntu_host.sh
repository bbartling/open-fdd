#!/usr/bin/env bash
# Safe Ubuntu host remediation helper for Open-FDD edge VMs.
# Default: dry-run (prints commands only). Use --apply to run apt upgrades.
# Never reboots or changes firewall rules without explicit flags.
#
#   ./scripts/security/remediate_ubuntu_host.sh              # dry-run
#   ./scripts/security/remediate_ubuntu_host.sh --apply      # apt update + full-upgrade
#   ./scripts/security/remediate_ubuntu_host.sh --apply --reboot-if-needed  # reboot if flag file exists
set -euo pipefail

APPLY=0
REBOOT=0
UPGRADE_HOST_PIP=0

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

run_cmd() {
  echo "+ $*"
  if [[ "$APPLY" == "1" ]]; then
    "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --reboot-if-needed) REBOOT=1; shift ;;
    --upgrade-host-pip) UPGRADE_HOST_PIP=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown: $1" >&2; usage 1 ;;
  esac
done

echo "Open-FDD Ubuntu host remediation — $(date '+%Y-%m-%d %H:%M:%S')"
if [[ "$APPLY" == "0" ]]; then
  echo "DRY-RUN mode (pass --apply to execute apt steps)"
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  case "${VERSION_ID:-}" in
    16.04|18.04)
      echo "ERROR: Ubuntu ${VERSION_ID} is EOL. Rebuild VM on 24.04 LTS — apt upgrade cannot fix SEoL." >&2
      exit 2
      ;;
  esac
fi

echo ""
echo "==> 1. Refresh package indexes"
run_cmd sudo apt update

echo ""
echo "==> 2. Full security upgrade (kernel, openssh, pip USNs, wheel, etc.)"
run_cmd sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y

echo ""
echo "==> 3. Host Python packages (optional — prefer apt over pip on Ubuntu)"
if [[ "$UPGRADE_HOST_PIP" == "1" ]]; then
  echo "Upgrading pip toolchain in user context (not system site-packages unless --break-system-packages)"
  run_cmd python3 -m pip install --user --upgrade "pip>=26.0" "setuptools>=75.0" "wheel>=0.45" "pyOpenSSL>=26.0.0" || \
    echo "WARN: pip upgrade blocked (PEP 668) — use: sudo apt install --only-upgrade python3-pip python3-openssl"
else
  echo "Skipped (pass --upgrade-host-pip to attempt pip/pyOpenSSL upgrade)"
  echo "Recommended: sudo apt install --only-upgrade python3-pip python3-openssl python3-wheel"
fi

echo ""
echo "==> 4. OpenSSH Terrapin (CVE-2023-48795) — verify after upgrade"
echo "    ssh -V"
echo "    sudo sshd -T | grep -Ei 'ciphers|macs|kexalgorithms'"
echo "    Rollback: keep /etc/ssh/sshd_config.bak before manual KEX/cipher edits"

echo ""
echo "==> 5. Ollama loopback bind (if systemd ollama unit exists)"
if systemctl list-unit-files ollama.service >/dev/null 2>&1; then
  echo "    Ensure /etc/systemd/system/ollama.service contains:"
  echo "      Environment=OLLAMA_HOST=127.0.0.1:11434"
  echo "    Then: sudo systemctl daemon-reload && sudo systemctl restart ollama"
  if [[ "$APPLY" == "1" ]] && grep -q 'OLLAMA_HOST=127.0.0.1:11434' /etc/systemd/system/ollama.service 2>/dev/null; then
    run_cmd sudo systemctl daemon-reload
    run_cmd sudo systemctl restart ollama
  fi
fi

echo ""
echo "==> 6. Reboot check"
if [[ -f /var/run/reboot-required ]]; then
  echo "REBOOT REQUIRED for kernel/OpenSSH updates"
  if [[ "$REBOOT" == "1" && "$APPLY" == "1" ]]; then
    echo "Rebooting in 10 seconds (Ctrl+C to cancel)…"
    sleep 10
    run_cmd sudo reboot
  else
    echo "Run manually after maintenance window: sudo reboot"
    echo "Or pass --apply --reboot-if-needed"
  fi
else
  echo "No reboot flag"
fi

echo ""
echo "==> 7. Post-remediation validation"
echo "    ./scripts/security/check_host_security.sh"
echo "    ./scripts/security/check_openfdd_exposure.sh"
echo "    uname -r"
echo "    Request IT Nessus rescan after reboot"

if [[ "$APPLY" == "0" ]]; then
  echo ""
  echo "Dry-run complete. Re-run with --apply when ready."
fi
