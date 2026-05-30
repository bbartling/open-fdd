#!/usr/bin/env bash
# E2E: Who-Is then add devices using addresses from I-Am (commission agent).
set -euo pipefail
BASE="${OPENFDD_BACNET_COMMISSION_URL:-http://127.0.0.1:8767}"

echo "Who-Is…"
WHO=$(curl -sf -X POST "$BASE/api/bacnet/whois" -H 'Content-Type: application/json' -d '{"range_low":1,"range_high":4194303}')
COUNT=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("count",0))' "$WHO")
echo "Found $COUNT device(s)"

wait_job() {
  local jid=$1
  for _ in $(seq 1 30); do
    sleep 1
    R=$(curl -sf "$BASE/api/jobs/$jid")
    ST=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("status",""))' "$R")
    if [[ "$ST" != "running" ]]; then
      python3 -c 'import json,sys; d=json.loads(sys.argv[1]); r=d.get("result") or {}; print(d.get("status"), len(r.get("objects") or []), d.get("error","")[:80])' "$R"
      return
    fi
  done
  echo "timeout job $jid"
}

python3 - <<'PY' "$WHO" "$BASE"
import json, sys, time, urllib.error, urllib.request

who = json.loads(sys.argv[1])
base = sys.argv[2]
devices = who.get("devices") or []
if not devices:
    print("No devices found from Who-Is", file=sys.stderr)
    sys.exit(1)

failed = False
for row in devices:
    ident = row.get("i-am-device-identifier") or ""
    inst = None
    if "device" in ident.lower():
        for part in ident.replace(",", " ").split():
            if part.isdigit():
                inst = int(part)
                break
    if inst is None:
        continue
    addr = str(row.get("device-address") or "")
    body = json.dumps({"device_instance": inst, "device_address": addr}).encode()
    req = urllib.request.Request(
        f"{base}/api/jobs/point-discovery",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            job = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"point-discovery failed for {inst}: HTTP {exc.code}", file=sys.stderr)
        failed = True
        continue
    jid = job["job_id"]
    print(f"Add device {inst} @ {addr} job={jid}")
    status = "running"
    for _ in range(30):
        time.sleep(1)
        with urllib.request.urlopen(f"{base}/api/jobs/{jid}", timeout=10) as resp:
            meta = json.loads(resp.read())
        status = meta.get("status") or ""
        if status != "running":
            n = len((meta.get("result") or {}).get("objects") or [])
            print(f"  -> {status} {n} points", meta.get("error") or "")
            break
    else:
        print(f"Job {jid} timed out still running", file=sys.stderr)
        failed = True
        continue
    if status != "success":
        err = meta.get("error") or status
        print(f"Job {jid} failed: {err}", file=sys.stderr)
        failed = True

if failed:
    sys.exit(1)
PY

echo "OK"
