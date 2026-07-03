#!/usr/bin/env bash
# Per-minute protocol activity from a bench pcap — validates poll cadence during soak.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCAP_DIR="${1:-$(cat "$ROOT/workspace/logs/pcap_latest.dir" 2>/dev/null || true)}"
PCAP="${PCAP_DIR}/openfdd_ot.pcap"
OUT="${PCAP_DIR}/minute_buckets.json"
SUMMARY="${PCAP_DIR}/minute_validate.txt"
BUCKET_SEC="${OPENFDD_PCAP_BUCKET_SEC:-60}"

MIN_BACNET="${OPENFDD_PCAP_MIN_BACNET:-1}"
MIN_MODBUS="${OPENFDD_PCAP_MIN_MODBUS:-1}"
MIN_HTTP8080="${OPENFDD_PCAP_MIN_HTTP8080:-3}"
MIN_HAYSTACK443="${OPENFDD_PCAP_MIN_HAYSTACK443:-0}"

[[ -f "$PCAP" ]] || { echo "ERROR: missing $PCAP" >&2; exit 1; }

count_buckets() {
  local filter="$1"
  docker run --rm -v "$PCAP_DIR:/pcap:ro" nicolaka/netshoot \
    sh -c "tcpdump -r /pcap/openfdd_ot.pcap -tt -n '$filter' 2>/dev/null" \
    | awk -v B="$BUCKET_SEC" '{ b=int($1/B); c[b]++ } END { for (k in c) print k, c[k] }' \
    | sort -n
}

bacnet_b="$(count_buckets 'udp port 47808' || true)"
modbus_b="$(count_buckets 'tcp port 1502' || true)"
http_b="$(count_buckets 'tcp port 8080' || true)"
hay_b="$(count_buckets 'tcp port 443' || true)"

json_obj() {
  local data="$1"
  [[ -n "$data" ]] || { echo '{}'; return; }
  echo "$data" | awk '{printf "\"%s\":%s,\n", $1, $2}' | sed '$ s/,$//' | awk 'BEGIN{print "{"} {print} END{print "}"}'
}

BACNET_JSON="$(json_obj "$bacnet_b")"
MODBUS_JSON="$(json_obj "$modbus_b")"
HTTP_JSON="$(json_obj "$http_b")"
HAY_JSON="$(json_obj "$hay_b")"

jq -nc \
  --argjson bucket "$BUCKET_SEC" \
  --argjson bacnet "$BACNET_JSON" \
  --argjson modbus "$MODBUS_JSON" \
  --argjson http8080 "$HTTP_JSON" \
  --argjson haystack443 "$HAY_JSON" \
  '{bucket_seconds:$bucket,bacnet:$bacnet,modbus:$modbus,http8080:$http8080,haystack443:$haystack443}' \
  >"$OUT"

FAIL=0
check_min() {
  local name="$1" min="$2" obj="$3"
  local bad total
  total="$(jq -r "$obj | length" "$OUT")"
  if [[ "$total" -eq 0 ]]; then
    if [[ "$min" -gt 0 ]]; then
      echo "FAIL $name: no packets in capture" | tee -a "$SUMMARY"
      FAIL=1
    else
      echo "SKIP $name: no traffic (min=0)" | tee -a "$SUMMARY"
    fi
    return
  fi
  bad="$(jq -r --argjson m "$min" "$obj | to_entries | map(select(.value < \$m)) | length" "$OUT")"
  if [[ "$bad" -gt 0 ]]; then
    echo "FAIL $name: $bad bucket(s) below min=$min" | tee -a "$SUMMARY"
    jq -r --argjson m "$min" "$obj | to_entries | map(select(.value < \$m))" "$OUT" | tee -a "$SUMMARY"
    FAIL=1
  else
    echo "PASS $name: $total active minute-bucket(s), all >= $min" | tee -a "$SUMMARY"
  fi
}

{
  echo "=== PCAP minute-bucket validation ==="
  echo "File: $PCAP"
  echo "Bucket: ${BUCKET_SEC}s"
  jq . "$OUT"
  echo
} | tee "$SUMMARY"

check_min bacnet "$MIN_BACNET" '.bacnet'
check_min modbus "$MIN_MODBUS" '.modbus'
check_min http8080 "$MIN_HTTP8080" '.http8080'
[[ "$MIN_HAYSTACK443" -gt 0 ]] && check_min haystack443 "$MIN_HAYSTACK443" '.haystack443'

jq -nc --arg pcap "$PCAP" --argjson fail "$FAIL" --slurpfile b "$OUT" \
  '{pcap:$pcap,minute_buckets:$b[0],passed:($fail==0)}' >"${PCAP_DIR}/minute_validate.json"

echo "Wrote $OUT"
[[ "$FAIL" -eq 0 ]]
