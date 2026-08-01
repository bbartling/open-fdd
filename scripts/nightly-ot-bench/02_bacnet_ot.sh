#!/usr/bin/env bash
# BACnet OT gates: Who-Is, 5007 routed read/discover, BIP companions, poll, hosted 599999.
# Recreates diy-bacnet-server smoke intent against openfdd-fieldbus :8081.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

DEV="${BENCH_DEVICE}"
READ_TYPE="${BENCH_READ_TYPE:-analog-input}"
READ_INST="${BENCH_READ_INST:-1173}"
OVR_TYPE="${BENCH_OVR_TYPE:-analog-output}"
OVR_INST="${BENCH_OVR_INST:-2466}"
EXPECT_PRIORITY="${BENCH_EXPECT_PRIORITY:-8}"
EXPECT_VALUE="${BENCH_EXPECT_VALUE:-55}"
HOSTED="${HOSTED_DEVICE}"

hdr "Who-Is"
if W="$(fb -X POST "$FIELDBUS_BASE/bacnet/whois" -d '{}' 2>/dev/null)"; then
  jq_ok "Who-Is returns ≥1 device" "$W" '(.count|tonumber) >= 1'
  jq_ok "Who-Is finds device $DEV" "$W" --arg d "$DEV" 'any(.devices[]; (.device_instance|tostring)==$d)'
  echo "${DIM}  devices=$(jq -c '[.devices[].device_instance]' <<<"$W" 2>/dev/null)${RST}"
  # Routed devices should report source_network when seed/API is correct
  if jq -e --argjson d "$DEV" 'any(.devices[]; .device_instance==$d and .source_network != null)' <<<"$W" >/dev/null 2>&1; then
    ok "device $DEV has source_network (routed seed looks correct)"
  else
    bad "device $DEV missing source_network — likely add_device-at-router instead of add_routed_device"
  fi
else
  bad "POST /bacnet/whois"
fi

hdr "Who-Is router"
if WR="$(fb -X POST "$FIELDBUS_BASE/bacnet/whois-router" -d '{}' 2>/dev/null)"; then
  net="${BENCH_MSTP_NETWORK:-2000}"
  jq_ok "whois-router lists network $net" "$WR" --argjson n "$net" 'any(.routers[]; (.networks[]|tonumber)==$n)'
  echo "${DIM}  $(jq -c '.routers' <<<"$WR" 2>/dev/null)${RST}"
else
  bad "POST /bacnet/whois-router"
fi

hdr "ReadProperty device $DEV $READ_TYPE:$READ_INST"
if R="$(fb -X POST "$FIELDBUS_BASE/bacnet/read" \
  -d "{\"device_instance\":$DEV,\"object_type\":\"$READ_TYPE\",\"object_instance\":$READ_INST}" 2>/dev/null)"; then
  jq_ok "read $DEV $READ_TYPE:$READ_INST has value" "$R" '.value != null and .ok==true'
  echo "${DIM}  value=$(jq -r .value <<<"$R") tag=$(jq -r .tag <<<"$R")${RST}"
else
  bad "read $DEV failed (routed MS/TP broken if UNKNOWN_OBJECT)"
fi

hdr "Point discovery $DEV"
if D="$(fb_long -X POST "$FIELDBUS_BASE/api/bacnet/point-discovery" \
  -d "{\"device_instance\":$DEV}" 2>/dev/null)"; then
  jq_ok "discovery finds $OVR_TYPE,$OVR_INST" "$D" --arg oi "$OVR_TYPE,$OVR_INST" \
    'any(.objects[]; .object_identifier==$oi)'
  jq_ok "$OVR_TYPE,$OVR_INST commandable" "$D" --arg oi "$OVR_TYPE,$OVR_INST" \
    'any(.objects[]; .object_identifier==$oi and .commandable==true)'
  echo "${DIM}  objects=$(jq -r '.objects|length' <<<"$D")${RST}"
else
  bad "POST /api/bacnet/point-discovery $DEV"
fi

hdr "Priority array / override (optional if operator left P8)"
if PA="$(fb -X POST "$FIELDBUS_BASE/bacnet/priority-array" \
  -d "{\"device_instance\":$DEV,\"object_type\":\"$OVR_TYPE\",\"object_instance\":$OVR_INST}" 2>/dev/null)"; then
  PV="$(jq -r --argjson p "$EXPECT_PRIORITY" \
    '.priority_array[]? | select(.priority_level==$p) | .value // empty' <<<"$PA")"
  if [[ -n "$PV" && "$PV" != "null" ]] && approx "$PV" "$EXPECT_VALUE"; then
    ok "priority $EXPECT_PRIORITY ≈ $EXPECT_VALUE (got $PV)"
  else
    skip "priority $EXPECT_PRIORITY not ≈ $EXPECT_VALUE (got '${PV:-empty}') — operator override may be cleared"
  fi
else
  skip "priority-array unreachable"
fi

hdr "BIP companions (if configured)"
for pair in \
  "${BIP_DEVICE_A:-}|${BIP_DEVICE_A_READ_TYPE:-analog-input}|${BIP_DEVICE_A_READ_INST:-}" \
  "${BIP_DEVICE_B:-}|${BIP_DEVICE_B_READ_TYPE:-analog-input}|${BIP_DEVICE_B_READ_INST:-}"; do
  IFS='|' read -r bdev btype binst <<<"$pair"
  [[ -z "$bdev" || -z "$binst" ]] && continue
  if R="$(fb -X POST "$FIELDBUS_BASE/bacnet/read" \
    -d "{\"device_instance\":$bdev,\"object_type\":\"$btype\",\"object_instance\":$binst}" 2>/dev/null)"; then
    jq_ok "BIP read $bdev $btype:$binst" "$R" '.value != null'
    echo "${DIM}  $bdev value=$(jq -r .value <<<"$R")${RST}"
  else
    bad "BIP read $bdev"
  fi
done

hdr "Poll once + status"
if P="$(fb -X POST "$FIELDBUS_BASE/bacnet/poll/once" 2>/dev/null)"; then
  jq_ok "poll/once ok" "$P" '.ok==true and (.points_polled|tonumber)>0'
  echo "${DIM}  $(jq -c '{points_polled,points_errored,cycle}' <<<"$P")${RST}"
else
  bad "poll/once"
fi
if S="$(fb "$FIELDBUS_BASE/bacnet/poll/status" 2>/dev/null)"; then
  jq_ok "poll/status has last_values" "$S" '(.last_values|length)>0'
  jq_ok "poll has live value for BIP or 5007" "$S" \
    --argjson d "$DEV" \
    'any(.last_values[]; .error==null and .value!=null)'
  # Strict: 5007 row must be healthy when routed fix lands
  if jq -e --argjson d "$DEV" \
    'any(.last_values[]; .device_instance==$d and .error==null and .value!=null)' <<<"$S" >/dev/null; then
    ok "poll last_values includes healthy $DEV"
  else
    bad "poll last_values missing healthy $DEV (routing/seed still broken)"
  fi
  echo "${DIM}  healthy=$(jq -r .points_healthy <<<"$S") tracked=$(jq -r .points_tracked <<<"$S")${RST}"
else
  bad "poll/status"
fi

hdr "Hosted server $HOSTED (Workbench)"
if O="$(fb "$FIELDBUS_BASE/bacnet/server/objects" 2>/dev/null)"; then
  jq_ok "hosted objects present" "$O" '(.objects|length) >= 1'
  echo "${DIM}  objects=$(jq -r '.objects|length' <<<"$O")${RST}"
else
  bad "GET /bacnet/server/objects"
fi

summary
