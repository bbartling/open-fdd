#!/usr/bin/env bash
# Railway hub capacity sampler helpers (Wave S S5a).
# Source from run_railway_hub_stress.sh — do not run alone as a gate.
#
# Env:
#   CAPACITY_SAMPLE=1|0     default 1 when RAILWAY_ONLY=1 else 0
#   CAPACITY_SAMPLE_SECS=15
#   CAPACITY_STRICT=0|1     promote soft warns → fail in report status
#   OPENFDD_API_BASE / OPENFDD_ADMIN_TOKEN / ARTIFACT_DIR
#   OPENFDD_STRESS_GATE     optional current gate id tag

capacity_sample_enabled() {
  local def=0
  [[ "${RAILWAY_ONLY:-0}" == "1" ]] && def=1
  [[ "${CAPACITY_SAMPLE:-$def}" == "1" ]]
}

capacity_sample_once() {
  local art="${ARTIFACT_DIR:-}"
  local base="${OPENFDD_API_BASE:-${CENTRAL_BASE:-}}"
  local tok="${OPENFDD_ADMIN_TOKEN:-}"
  local gate="${OPENFDD_STRESS_GATE:-}"
  [[ -n "$art" && -n "$base" ]] || return 0
  mkdir -p "$art"
  python3 - "$base" "$tok" "$art/capacity_samples.ndjson" "$gate" <<'PY'
import json, os, sys, time, urllib.error, urllib.request

base, tok, path, gate = sys.argv[1:5]
headers = {"Accept": "application/json"}
if tok:
    headers["Authorization"] = f"Bearer {tok}"

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body
    except Exception as e:
        return 0, str(e)

def try_json(status, body):
    try:
        return json.loads(body) if body else {}
    except Exception:
        return {"_raw": body[:500], "_http": status}

hs, hb = get(base.rstrip("/") + "/api/health")
ss, sb = get(base.rstrip("/") + "/api/host/stats")
ds, db = get(base.rstrip("/") + "/api/data-management/summary")
health = try_json(hs, hb)
host = try_json(ss, sb)
dms = try_json(ds, db)

mem = host.get("memory") if isinstance(host.get("memory"), dict) else {}
storage = host.get("storage") if isinstance(host.get("storage"), dict) else {}
# Prefer nested data_management on host/stats when present
dm = host.get("data_management") if isinstance(host.get("data_management"), dict) else {}
if not dm and isinstance(dms, dict):
    dm = dms

file_count = (
    dm.get("file_count")
    or dm.get("files")
    or dm.get("parquet_files")
    or (dm.get("total_row_count") if False else None)
)
# walk common keys
small_files = dm.get("small_files") or dm.get("small_file_count")
bytes_v = dm.get("estimated_bytes") or dm.get("total_bytes") or dm.get("bytes")
if storage.get("used_bytes") is not None and bytes_v is None:
    bytes_v = storage.get("used_bytes")

mem_total = mem.get("total_bytes")
memory_source = "host_proc"
if mem_total and int(mem_total) > 64 * 1024**3:
    memory_source = "host_proc_likely_shared_node"

sample = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "gate": gate or None,
    "health_http": hs,
    "health_ok": bool(health.get("ok")) if isinstance(health, dict) else False,
    "ingest_ok": health.get("ingest_ok") if isinstance(health, dict) else None,
    "edges": health.get("edges") if isinstance(health, dict) else None,
    "uptime_secs": health.get("uptime_secs") if isinstance(health, dict) else None,
    "host_http": ss,
    "memory_percent_used": mem.get("percent_used"),
    "memory_total_bytes": mem_total,
    "memory_used_bytes": mem.get("used_bytes"),
    "memory_source": memory_source,
    "storage_used_bytes": storage.get("used_bytes"),
    "storage_percent_used": storage.get("percent_used"),
    "historian_file_count": file_count,
    "historian_small_files": small_files,
    "historian_bytes": bytes_v,
    "dm_http": ds,
}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(sample, separators=(",", ":")) + "\n")
PY
}

capacity_sampler_start() {
  capacity_sample_enabled || return 0
  local art="${ARTIFACT_DIR:?}"
  local secs="${CAPACITY_SAMPLE_SECS:-15}"
  mkdir -p "$art"
  : >"$art/capacity_samples.ndjson"
  capacity_sample_once || true
  (
    while true; do
      sleep "$secs"
      capacity_sample_once || true
    done
  ) &
  export CAPACITY_SAMPLER_PID=$!
  echo "$CAPACITY_SAMPLER_PID" >"$art/capacity_sampler.pid"
  echo "capacity sampler pid=$CAPACITY_SAMPLER_PID interval=${secs}s" >&2
}

capacity_sampler_stop() {
  local art="${ARTIFACT_DIR:-}"
  local pid="${CAPACITY_SAMPLER_PID:-}"
  if [[ -z "$pid" && -n "$art" && -f "$art/capacity_sampler.pid" ]]; then
    pid="$(cat "$art/capacity_sampler.pid" 2>/dev/null || true)"
  fi
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  unset CAPACITY_SAMPLER_PID
  capacity_sample_once || true
}

capacity_write_hub_env() {
  local art="${ARTIFACT_DIR:?}"
  mkdir -p "$art"
  # Values are safe operational knobs (not secrets).
  python3 - "$art/hub_env_capacity.json" <<'PY'
import json, os, sys
out = sys.argv[1]
payload = {
    "OPENFDD_QUERY_MEMORY_MB": os.environ.get("OPENFDD_QUERY_MEMORY_MB")
    or os.environ.get("HUB_OPENFDD_QUERY_MEMORY_MB"),
    "OPENFDD_DATAFUSION_SPILL_DIR_set": bool(
        os.environ.get("OPENFDD_DATAFUSION_SPILL_DIR")
        or os.environ.get("HUB_OPENFDD_DATAFUSION_SPILL_DIR")
    ),
    "CAPACITY_SAMPLE": os.environ.get("CAPACITY_SAMPLE", ""),
    "CAPACITY_SAMPLE_SECS": os.environ.get("CAPACITY_SAMPLE_SECS", "15"),
    "CAPACITY_STRICT": os.environ.get("CAPACITY_STRICT", "0"),
    "note": "Prefer recording hub vars via railway CLI into this file when available",
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")
PY
}

capacity_fetch_hub_env_railway() {
  local art="${ARTIFACT_DIR:?}"
  command -v railway >/dev/null 2>&1 || return 0
  local svc="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
  local tmp
  tmp="$(mktemp)"
  if env -u RAILWAY_TOKEN railway variable list --service "$svc" --json >"$tmp" 2>/dev/null; then
    python3 - "$tmp" "$art/hub_env_capacity.json" <<'PY'
import json, sys
src, out = sys.argv[1:3]
d = json.load(open(src))
payload = {
    "OPENFDD_QUERY_MEMORY_MB": d.get("OPENFDD_QUERY_MEMORY_MB"),
    "OPENFDD_DATAFUSION_SPILL_DIR": d.get("OPENFDD_DATAFUSION_SPILL_DIR"),
    "OPENFDD_DATAFUSION_SPILL_DIR_set": bool(d.get("OPENFDD_DATAFUSION_SPILL_DIR")),
    "CAPACITY_SAMPLE": True,
    "note": "from railway variable list (central)",
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")
PY
  fi
  rm -f "$tmp"
}

capacity_write_report() {
  local art="${ARTIFACT_DIR:?}"
  local strict="${CAPACITY_STRICT:-0}"
  python3 - "$art/capacity_samples.ndjson" "$art/capacity_report.json" "$strict" <<'PY'
import json, sys
from pathlib import Path

nd, out, strict = sys.argv[1:4]
strict = strict == "1"
path = Path(nd)
samples = []
if path.is_file():
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except Exception:
            pass

soft_warns = []
hard_fails = []
info = []

def nums(key):
    vals = []
    for s in samples:
        v = s.get(key)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return vals

baseline = samples[0] if samples else {}
last = samples[-1] if samples else {}

def peak(key):
    vs = nums(key)
    return max(vs) if vs else None

def delta(key):
    if not samples:
        return None
    a, b = baseline.get(key), last.get(key)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return b - a
    return None

health_oks = [bool(s.get("health_ok")) for s in samples]
flaps = 0
for i in range(1, len(health_oks)):
    if health_oks[i] != health_oks[i - 1]:
        flaps += 1
if samples and not health_oks[-1]:
    hard_fails.append("health_ok false at end of run")
if flaps >= 2:
    hard_fails.append(f"health_ok flaps={flaps}")

mem_src = last.get("memory_source") or baseline.get("memory_source")
if mem_src == "host_proc_likely_shared_node":
    info.append("memory_source=host_proc_likely_shared_node — do not FAIL on memory_percent_used alone")

sf0 = baseline.get("historian_small_files")
sf1 = last.get("historian_small_files")
fc0 = baseline.get("historian_file_count")
fc1 = last.get("historian_file_count")
b0 = baseline.get("historian_bytes")
b1 = last.get("historian_bytes")
if (
    isinstance(sf0, (int, float))
    and isinstance(sf1, (int, float))
    and sf1 > sf0 + 100
    and isinstance(b0, (int, float))
    and isinstance(b1, (int, float))
    and abs(b1 - b0) < max(1_000_000, 0.05 * max(b0, 1))
):
    soft_warns.append(
        f"small_files grew {sf0}->{sf1} while historian_bytes nearly flat ({b0}->{b1})"
    )
elif (
    isinstance(fc0, (int, float))
    and isinstance(fc1, (int, float))
    and fc1 > fc0 + 500
    and isinstance(b0, (int, float))
    and isinstance(b1, (int, float))
    and abs(b1 - b0) < max(1_000_000, 0.05 * max(b0, 1))
):
    soft_warns.append(
        f"file_count grew {fc0}->{fc1} while historian_bytes nearly flat ({b0}->{b1})"
    )

sp = peak("storage_percent_used")
if sp is not None and sp > 80:
    soft_warns.append(f"storage_percent_used peak={sp} > 80")

by_gate = {}
for s in samples:
    g = s.get("gate") or "_ungated"
    by_gate.setdefault(g, 0)
    by_gate[g] += 1

status = "ok"
if hard_fails:
    status = "hard_fail"
elif soft_warns:
    status = "soft_warn"
if strict and soft_warns and status == "soft_warn":
    status = "hard_fail"
    hard_fails.append("CAPACITY_STRICT=1 promoted soft_warns")

report = {
    "ok": status == "ok",
    "status": status,
    "sample_count": len(samples),
    "baseline": baseline,
    "last": last,
    "peak_memory_percent_used": peak("memory_percent_used"),
    "peak_storage_used_bytes": peak("storage_used_bytes"),
    "delta_storage_used_bytes": delta("storage_used_bytes"),
    "peak_historian_file_count": peak("historian_file_count"),
    "delta_historian_file_count": delta("historian_file_count"),
    "peak_historian_small_files": peak("historian_small_files"),
    "delta_historian_small_files": delta("historian_small_files"),
    "delta_ingest_ok": delta("ingest_ok"),
    "health_ok_flaps": flaps,
    "samples_by_gate": by_gate,
    "soft_warns": soft_warns,
    "hard_fails": hard_fails,
    "info": info,
}
Path(out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(f"capacity_report status={status} samples={len(samples)} soft={len(soft_warns)} hard={len(hard_fails)}")
if status == "hard_fail":
    sys.exit(2)
PY
}
