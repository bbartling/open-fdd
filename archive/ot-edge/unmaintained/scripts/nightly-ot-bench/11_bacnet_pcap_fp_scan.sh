#!/usr/bin/env bash
# Capture BACnet/IP and scan for known anti-patterns from bad_rusty_bacnet_app
# (FP-1 Who-Is storms, ephemeral broadcast, etc.).
#
# Live capture uses privileged docker tcpdump (host often lacks CAP_NET_RAW/sudo),
# then rusty-bacnet `bacnet capture --read … --decode` for FP heuristics.
#
# Env:
#   OT_NIC              — capture device (default enp3s0)
#   BACNET_CLI          — path to bacnet binary (default: bacnet on PATH)
#   PCAP_SECONDS        — live capture duration (default: 120)
#   PCAP_OUT            — output pcap path (default under ARTIFACT_DIR)
#   PCAP_DOCKER_IMAGE   — image with tcpdump (default: nicolaka/netshoot)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
NIC="${OT_NIC:-enp3s0}"
CLI="${BACNET_CLI:-bacnet}"
SECS="${PCAP_SECONDS:-120}"
OUT="${PCAP_OUT:-$ART/ot_bench.pcap}"
DECODE_LOG="$ART/bacnet_capture_decode.txt"
FP_LOG="$ART/bacnet_fp_scan.txt"
ERR="$ART/bacnet_capture_err.txt"
IMG="${PCAP_DOCKER_IMAGE:-nicolaka/netshoot}"

hdr "BACnet pcap capture + FP scan (rusty-bacnet CLI)"

resolve_cli() {
  if [[ -x "$CLI" ]]; then
    echo "$CLI"
    return 0
  fi
  if command -v "$CLI" >/dev/null 2>&1; then
    command -v "$CLI"
    return 0
  fi
  return 1
}

if ! CLI_PATH="$(resolve_cli)"; then
  skip "bacnet CLI not found (set BACNET_CLI). Install: https://github.com/jscott3201/rusty-bacnet/releases"
  summary
  exit 0
fi

echo "${DIM}device=$NIC duration=${SECS}s out=$OUT cli=$CLI_PATH${RST}"
: >"$ERR"
rm -f "$OUT"

# Light OT traffic during capture — prefer ReadProperty / poll, not Who-Is spam
# (Who-Is every 2s would falsely trip FP-1 heuristics).
traffic_loop() {
  local end=$((SECONDS + SECS - 1))
  while (( SECONDS < end )); do
    fb -X POST "$FIELDBUS_BASE/bacnet/poll/once" -d '{}' >/dev/null 2>&1 || true
    fb -X POST "$FIELDBUS_BASE/bacnet/read" \
      -d '{"device_instance":5007,"object_type":"analog-input","object_instance":1173}' \
      >/dev/null 2>&1 || true
    sleep 5
  done
}

capture_ok=0

# 1) passwordless sudo + bacnet --save
if timeout "$SECS" sudo -n "$CLI_PATH" capture --device "$NIC" --save "$OUT" --quiet 2>>"$ERR"; then
  if [[ -s "$OUT" ]]; then
    capture_ok=1
    ok "pcap saved via sudo -n bacnet capture"
  fi
fi

# 2) privileged docker tcpdump (reliable on this bench without host sudo)
if [[ "$capture_ok" -eq 0 ]]; then
  echo "${DIM}trying privileged docker tcpdump…${RST}"
  OUT_DIR="$(cd "$(dirname "$OUT")" && pwd)"
  OUT_BASE="$(basename "$OUT")"
  traffic_loop &
  TPID=$!
  # shellcheck disable=SC2064
  trap "kill $TPID 2>/dev/null || true" EXIT
  if docker run --rm --privileged --network host \
    -v "$OUT_DIR:/out" \
    "$IMG" \
    sh -c "timeout '$SECS' tcpdump -i '$NIC' -nn -c 5000 'udp port 47808' -w '/out/$OUT_BASE' 2>/out/tcpdump_capture_err.txt; echo tcpdump_rc=\$?" \
    >>"$ERR" 2>&1; then
    :
  fi
  # tcpdump err already under ART when OUT_DIR == ART
  if [[ -f "$OUT_DIR/tcpdump_capture_err.txt" && "$OUT_DIR" != "$ART" ]]; then
    mv -f "$OUT_DIR/tcpdump_capture_err.txt" "$ART/" || true
  fi
  kill "$TPID" 2>/dev/null || true
  wait "$TPID" 2>/dev/null || true
  trap - EXIT
  if [[ -s "$OUT" ]]; then
    capture_ok=1
    ok "pcap saved via privileged docker tcpdump ($(wc -c <"$OUT") bytes)"
  fi
fi

if [[ "$capture_ok" -eq 0 || ! -s "$OUT" ]]; then
  bad "bacnet/tcpdump capture failed or empty (need sudo/--privileged). See $ERR"
  summary
  exit 1
fi

"$CLI_PATH" capture --read "$OUT" --decode >"$DECODE_LOG" 2>&1 || true
ok "decode log → $DECODE_LOG ($(wc -l <"$DECODE_LOG") lines)"

# Heuristic FP scan (align with bad_rusty_bacnet_app README FPs).
python3 - "$DECODE_LOG" "$FP_LOG" <<'PY'
import re, sys, json
log_path, out_path = sys.argv[1], sys.argv[2]
text = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
whois = [ln for ln in text if re.search(r"\bWHO_IS\b", ln, re.I)]
iam = [ln for ln in text if re.search(r"\bI_AM\b", ln, re.I)]
rp = [ln for ln in text if re.search(r"\bREAD_PROPERTY\b", ln, re.I)]
# Ephemeral broadcast: Who-Is to *.*.*.*:port where port != 47808
ephemeral = []
for ln in whois:
    m = re.search(r"->\s+(\d+\.\d+\.\d+\.\d+):(\d+)", ln)
    if m and m.group(2) != "47808":
        ephemeral.append(ln)
ratio = (len(whois) / max(len(rp), 1))
findings = []
if len(ephemeral) >= 3:
    findings.append(f"FP-ephemeral-broadcast: {len(ephemeral)} Who-Is not to :47808")
if len(whois) >= 20 and ratio >= 0.5:
    findings.append(f"FP-1/6-whois-storm: whois={len(whois)} read_property={len(rp)} ratio={ratio:.2f}")
if not text:
    findings.append("empty-decode-log")
report = {
    "whois": len(whois),
    "i_am": len(iam),
    "read_property": len(rp),
    "whois_per_rp": round(ratio, 3),
    "ephemeral_whois": len(ephemeral),
    "findings": findings,
    "ok": len(findings) == 0,
}
open(out_path, "w", encoding="utf-8").write(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
sys.exit(0 if report["ok"] else 2)
PY
rc=$?
if [[ "$rc" -eq 0 ]]; then
  ok "pcap FP scan clean (no Who-Is storm / ephemeral broadcast signatures)"
else
  bad "pcap FP signatures detected — see $FP_LOG (compare bad_rusty_bacnet_app)"
fi

summary
exit "$rc"
