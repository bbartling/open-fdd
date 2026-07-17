# Linux edge tester — second-bench GHCR soak (paste into Cursor)

**Repo-only.** Paste into Cursor on a **second** OT / integration bench after product ships green `openfdd-{central,ui,fieldbus,mqtt}:nightly`.

Charter parent: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md) · stack short form: [linux-edge-tester-stack-nightly-prompt.md](./linux-edge-tester-stack-nightly-prompt.md)

This prompt is **more rigorous** than the stack short form: immutable digests, repeated 5007 sampling, failure handling, artifacts, and **leave-running** handoff for human Niagara / Workbench integration.

---

## Compact charter block (paste into Cursor)

```
You are the Open-FDD Linux edge tester on a SECOND bench at /home/ben/open-fdd
(or this host's open-fdd checkout).

Charter: TEST, DOCUMENT, REPORT — no Rust/TS product edits, no git push, no upstream PR.
GHCR pull only for openfdd-central / ui / fieldbus / mqtt :nightly (or matching sha-* pins).
Never docker build product images. Never cargo build the product.

Goals:
1) Pull coordinated nightlies and prove stack health with evidence.
2) Rigorous BACnet MS/TP device 5007 driver validation (discovery + present-value + telemetry).
3) Leave the stack RUNNING long-term after automated gates (do NOT compose down).
4) Hand off to HUMAN for Niagara/Workbench integration of hosted BACnet server 599999.

NEVER claim BACnet OT PASS from curl/API alone.
Record: Workbench: PASS (human) | FAIL (human) | NOT RUN
Until human evidence exists: OT PASS: NOT RUN

Acknowledged. Channel: second-bench GHCR soak. Comment evidence on #502 (or current nightly issue).
No git push. No product code edits on bench.
```

---

## Non-negotiables

| Rule | Detail |
|------|--------|
| Images | Pull GHCR only — never local `docker build` of central/ui/fieldbus/mqtt |
| Tear-down | After tests: **leave stack up**. Do not `docker compose down` / `-v` unless human orders abort |
| BACnet OT | Hosted **599999** discoverability = **human** on another LAN host (Niagara / YABE / Workbench) |
| Evidence | Every PASS needs command + captured output path under `workspace/reports/bench-soak/` |
| Secrets | Never commit `.env`, JWT secrets, or passwords |

---

## PHASE 0 — Confirm nightlies are consumable

Record master tip and last green stack publish:

```bash
cd /home/ben/open-fdd
mkdir -p workspace/reports/bench-soak
REPO=bbartling/open-fdd

gh api repos/$REPO/commits/master --jq '{sha: .sha[0:12], msg: .commit.message[0:100]}' \
  | tee workspace/reports/bench-soak/00-master-tip.json

gh run list --repo "$REPO" --workflow "Publish Open-FDD stack to GHCR" --branch master --limit 5 \
  --json databaseId,status,conclusion,headSha,createdAt,url \
  | tee workspace/reports/bench-soak/00-stack-publish.json

# Proceed only when latest relevant publish conclusion == success
```

**Optional pins** (preferred for reproducible soak): read `docker/VERSION_MANIFEST.md` and export `sha-*` tags. Otherwise use `:nightly` only after publish success on the SHA you intend to test.

```bash
# Example pin form (replace after inspect):
# export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-<7>
# export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-<7>
# export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-<7>
# export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-<7>

export OPENFDD_CENTRAL_IMAGE=${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:nightly}
export OPENFDD_UI_IMAGE=${OPENFDD_UI_IMAGE:-ghcr.io/bbartling/openfdd-ui:nightly}
export OPENFDD_FIELDBUS_IMAGE=${OPENFDD_FIELDBUS_IMAGE:-ghcr.io/bbartling/openfdd-fieldbus:nightly}
export OPENFDD_MQTT_IMAGE=${OPENFDD_MQTT_IMAGE:-ghcr.io/bbartling/openfdd-mqtt:nightly}
```

Pull and capture digests:

```bash
set -a && source .env && set +a
for img in "$OPENFDD_CENTRAL_IMAGE" "$OPENFDD_UI_IMAGE" "$OPENFDD_FIELDBUS_IMAGE" "$OPENFDD_MQTT_IMAGE"; do
  docker pull "$img"
done

{
  echo "pulled_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for img in "$OPENFDD_CENTRAL_IMAGE" "$OPENFDD_UI_IMAGE" "$OPENFDD_FIELDBUS_IMAGE" "$OPENFDD_MQTT_IMAGE"; do
    echo "=== $img ==="
    docker image inspect "$img" --format '{{.Id}} {{index .RepoDigests 0}} {{.Architecture}}'
  done
} | tee workspace/reports/bench-soak/01-image-digests.txt
```

**PASS:** all four pulls succeed; digests recorded.

---

## PHASE 1 — Deploy stack (recreate, then leave running)

Use standalone compose + local overlay (bench `.env` must include OT NIC, BACnet seed for **5007**, JWT if testing remote UI):

```bash
# In .env (do not commit):
# OPENFDD_JWT_SECRET=<long-random>
# OPENFDD_ADMIN_PASSWORD=<bench-password>
# BACnet / MQTT / OT NIC settings per site overlay

docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml pull
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml up -d --remove-orphans
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml ps \
  | tee workspace/reports/bench-soak/02-compose-ps.txt
```

Wait for healthy:

```bash
for i in $(seq 1 60); do
  c=$(curl -fsS http://127.0.0.1:8080/api/health 2>/dev/null || true)
  f=$(curl -fsS http://127.0.0.1:8081/api/health 2>/dev/null || true)
  echo "try $i central=$(echo "$c" | head -c 80) fieldbus=$(echo "$f" | head -c 80)"
  echo "$c" | grep -q . && echo "$f" | grep -q . && break
  sleep 5
done
curl -fsS http://127.0.0.1:8080/api/health | tee workspace/reports/bench-soak/03-central-health.json
curl -fsS http://127.0.0.1:8081/api/health | tee workspace/reports/bench-soak/03-fieldbus-health.json
# OpenAPI must not crash central (post-#502)
curl -fsS -o /tmp/openapi.json -w "%{http_code}\n" http://127.0.0.1:8080/openapi.json \
  | tee workspace/reports/bench-soak/03-openapi-code.txt
test -s /tmp/openapi.json
```

**PASS:** all four containers running/healthy; central + fieldbus health OK; openapi returns body; **no restart loop** (`docker inspect` RestartCount stable over 2 minutes).

---

## PHASE 2 — Device 5007 BACnet driver validation (rigorous)

Target (adjust only if bench overlay differs; do not invent IDs):

| Item | Expect |
|------|--------|
| Device instance | **5007** |
| Transport | MS/TP via router (typical bench: net **2000**, MAC **`[7]`**) |
| Sample point | OA-T (or site-mapped AI) present-value readable |

### 2a — Discovery / registry

```bash
# Capture driver tree / device list (paths may vary by build — use fieldbus Swagger/OpenAPI if unsure)
curl -fsS http://127.0.0.1:8081/api/bacnet/driver/tree 2>/dev/null \
  | tee workspace/reports/bench-soak/04-bacnet-tree.json || true
# Prefer authenticated central proxy if JWT required:
# curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/... 
```

Evidence must show **5007** present with routed address (not missing / not UNKNOWN_OBJECT-only).

### 2b — Present-value reads (repeat 3× over ≥3 minutes)

```bash
for n in 1 2 3; do
  echo "=== sample $n at $(date -u +%H:%M:%S) ===" | tee -a workspace/reports/bench-soak/05-5007-reads.txt
  # Use the bench's known-good read path for device 5007 OA-T (AI:1173 or mapped id).
  # Example patterns (adapt to this build's API — do not invent success):
  # curl -fsS ".../present-value..." | tee -a workspace/reports/bench-soak/05-5007-reads.txt
  sleep 60
done
```

**PASS criteria for 5007:**

1. Device is discovered / registered with correct routing
2. Known object read succeeds **without** `UNKNOWN_OBJECT`
3. Numeric / non-null present-value on **at least 3 samples** spaced ≥60s
4. Corresponding MQTTS telemetry (if enabled) has non-null `value` / `present_value` for the healthy point
5. Central ingest / Feather historian grows (file mtime or row growth) after samples

**FAIL → stop automated PASS claims**, keep stack up for diagnosis unless network is endangered (PCAP Who-Is storm), comment evidence, do not proceed to “ready for human OT”.

### 2c — Optional PCAP gate (if OT NIC capture available)

If this bench historically sees Who-Is storms, run the existing PCAP script **before** long soak. **0 TX to broadcast storm**, peak pkt/s within site limits. FAIL → stop stack only if network is at risk; otherwise leave up and escalate.

---

## PHASE 3 — UI / auth gates

```bash
curl -fsS http://127.0.0.1:3000/ | head -c 200 | tee workspace/reports/bench-soak/06-ui-root.txt
curl -fsS http://127.0.0.1:8080/api/auth/status | tee workspace/reports/bench-soak/06-auth-status.json
```

Remote UI from another LAN host: `http://<bench-lan-ip>:3000/login`

- If JWT configured: login `admin` / `OPENFDD_ADMIN_PASSWORD`
- Record: `Remote UI: PASS | FAIL | NOT RUN`

Lab UI (vibe19): open `/lab` when stack UI includes it — registry count should be ≥59 when `sql_rules` shipped in images. Optional: `GET /api/fdd/rules` via central.

---

## PHASE 4 — Leave-running handoff (mandatory)

**Do not tear down.** Verify restart policy and health, then freeze a handoff sheet:

```bash
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml ps \
  | tee workspace/reports/bench-soak/99-leave-running-ps.txt

{
  echo "handoff_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "intent=LEAVE_RUNNING_FOR_HUMAN_WORKBENCH"
  echo "central_url=http://127.0.0.1:8080"
  echo "fieldbus_url=http://127.0.0.1:8081"
  echo "ui_url=http://127.0.0.1:3000"
  echo "hosted_bacnet_device=599999"
  echo "hosted_bacnet_udp=47808"
  echo "bench_device_under_test=5007"
  echo "images:"
  echo "  $OPENFDD_CENTRAL_IMAGE"
  echo "  $OPENFDD_UI_IMAGE"
  echo "  $OPENFDD_FIELDBUS_IMAGE"
  echo "  $OPENFDD_MQTT_IMAGE"
  echo "artifacts=workspace/reports/bench-soak/"
  echo "compose_torn_down=NO"
} | tee workspace/reports/bench-soak/99-handoff.txt
```

Agent closing statement must include:

```
AUTOMATED CHECKS: PASS | FAIL
OT PASS: NOT RUN   # until human Workbench/Niagara evidence
compose_torn_down: NO
```

---

## PHASE 5 — Human Niagara / Workbench gate (mandatory for OT PASS)

Human (not the agent), from a **different LAN host**:

1. Open Niagara Workbench, YABE, or equivalent BACnet browser
2. Who-Is / discover **hosted Open-FDD device 599999** on OT NIC UDP **47808**
3. Confirm hosted points look sane (present values)
4. Optionally bind / integrate the server object into the Niagara station for long-term monitoring while the stack stays up

Record exactly one of:

| Result | Meaning |
|--------|---------|
| `Workbench: PASS (human)` | 599999 discovered + points OK |
| `Workbench: FAIL (human)` | Not discoverable or bad points |
| `Workbench: NOT RUN` | Human has not run the gate |

**Agent must never upgrade `OT PASS: NOT RUN` to PASS without that human line.**

---

## Scorecard

| Gate | Evidence | Result |
|------|----------|--------|
| Four GHCR images pulled + digests | `01-image-digests.txt` | |
| Compose healthy / no restart loop | `02` + inspect | |
| Central health + openapi | `03-*` | |
| Fieldbus health | `03-fieldbus-health.json` | |
| Device **5007** discovery + routed read | `04` + `05` | |
| 5007 present-value ×3 (≥60s apart, non-null) | `05-5007-reads.txt` | |
| MQTT / central ingest (if enabled) | logs / Feather growth | |
| Remote UI login | human or scripted | |
| Stack left running | `99-handoff.txt` `compose_torn_down=NO` | |
| Workbench **599999** | human only | `NOT RUN` until human |

---

## Failure handling

| Failure | Action |
|---------|--------|
| Pull / digest mismatch | Stop; comment GH with tip SHA + publish run URL |
| Central restart loop / openapi crash | Capture logs; leave containers for product agent; do not claim PASS |
| 5007 UNKNOWN_OBJECT / null values | Capture API JSON; keep stack up; escalate |
| Who-Is storm / OT network risk | Stop BACnet poll / stack per site procedure; escalate immediately |
| Human Workbench FAIL | Keep stack up for debug; `OT PASS: FAIL (human)` |

---

## GitHub comment template

```markdown
## Second-bench GHCR soak

**SHA / tags:** …
**Digests:** (attach 01-image-digests.txt)
**Automated:** PASS | FAIL
**5007:** PASS | FAIL (samples …)
**Leave-running:** YES (`compose_torn_down=NO`)
**Workbench 599999:** PASS (human) | FAIL (human) | NOT RUN
**OT PASS:** NOT RUN  # or PASS (human) only after Workbench line

Artifacts: `workspace/reports/bench-soak/`
```
