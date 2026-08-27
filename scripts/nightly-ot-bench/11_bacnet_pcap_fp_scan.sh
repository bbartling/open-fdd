#!/usr/bin/env bash
# Capture BACnet/IP with rusty-bacnet `bacnet capture` and scan for known anti-patterns
# from bad_rusty_bacnet_app (FP-1 Who-Is storms, ephemeral broadcast, etc.).
#
# Env:
#   OT_NIC              — capture device (default from bench.env / enp3s0)
#   BACNET_CLI          — path to bacnet binary (default: bacnet on PATH)
#   PCAP_SECONDS        — live capture duration (default: 120)
#   PCAP_OUT            — output pcap path (default under ARTIFACT_DIR)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
NIC="${OT_NIC:-enp3s0}"
CLI="${BACNET_CLI:-bacnet}"
SECS="${PCAP_SECONDS:-120}"
OUT="${PCAP_OUT:-$ART/ot_bench.pcap}"
DECODE_LOG="$ART/bacnet_capture_decode.txt"
FP_LOG="$ART/bacnet_fp_scan.txt"

hdr "BACnet pcap capture + FP scan (rusty-bacnet CLI)"

if ! command -v "$CLI" >/dev/null 2>&1 && [[ ! -x "$CLI" ]]; then
  skip "bacnet CLI not found (set BACNET_CLI). Install: https://github.com/jscott3201/rusty-bacnet/releases"
  summary
  exit 0
fi

echo "${DIM}device=$NIC duration=${SECS}s out=$OUT${RST}"
# Live capture requires privileges on most hosts.
if timeout "$SECS" sudo -n "$CLI" capture --device "$NIC" --save "$OUT" --quiet 2>"$ART/bacnet_capture_err.txt"; then
  ok "pcap saved $OUT ($(wc -c <"$OUT") bytes)"
elif timeout "$SECS" "$CLI" capture --device "$NIC" --save "$OUT" --quiet 2>"$ART/bacnet_capture_err.txt"; then
  ok "pcap saved $OUT (no sudo)"
else
  bad "bacnet capture failed (need sudo/capabilities?). See bacnet_capture_err.txt"
  summary
  exit 1
fi

"$CLI" capture --read "$OUT" --decode >"$DECODE_LOG" 2>&1 || true
ok "decode log → $DECODE_LOG ($(wc -l <"$DECODE_LOG") lines)"

# Heuristic FP scan (align with bad_rusty_bacnet_app README FPs).
python3 - "$DECODE_LOG" "$FP_LOG" <<'PY'
import re, sys
from collections import Counter
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
# Burst: many Who-Is relative to ReadProperty (FP-1 / FP-6 style storms)
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
import json
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
