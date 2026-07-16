# Linux edge tester — GO NUTS when `:nightly` ready (paste prompt)

**Repo-only.** Paste into Cursor on **`/home/ben/open-fdd`** when product has merged **3.2.13** (PCAP Who-Is storm fix) and you are waiting for GHCR `:nightly` before bench deploy.

**Do not deploy 802258a (3.2.11) or 40fecf7 (3.2.12) on OT bench** — PCAP proved Who-Is broadcast storms take the MSTP network down. Wait for **3.2.13+** with PCAP gate.

**Related:** [nightly retest gates](./linux-edge-tester-nightly-retest-prompt.md) · [GH Actions watch](./linux-edge-tester-gh-actions-watch-prompt.md) · [issue index](./WSL_CURSOR_AGENT_ISSUES.md) · umbrella [#429](https://github.com/bbartling/open-fdd/issues/429) · [#464](https://github.com/bbartling/open-fdd/issues/464)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Bench has insufficient RAM — GHCR pull only (never docker build / cargo build).

PHASE 1 — Wait for :nightly (do not deploy until GHCR green on 3.2.13+ PCAP fix).
PHASE 2 — When ready: deploy, PCAP gate FIRST, then EVERY gate below, 30m FDD if P0 pass, post evidence on GitHub.

Acknowledged. Bench /home/ben/open-fdd. Channel: nightly. Minimum: 3.2.13 PCAP no-Who-Is-storm build.
Blockers: 0 TX to .255 in 5m PCAP, peak ≤15 pkt/s, MSTP 5007 on bridge, FDD without site.local.toml.
Set OPENFDD_BACNET_COMMISSION_OWNS_POLL=1 on bridge (full-edge bench).
Will comment #429, #464, #466, #465, #467, #469 as applicable.
No git push. No product code edits on bench.
```

**Human BACnet Workbench gate (every run):** ask the human to confirm from another machine that hosted device **599999** (UDP 47808 on OT NIC) is discoverable and points look good in YABE/Workbench. Agent records `Workbench: PASS (human)` — do not invent this from curl.

**Remote UI:** `http://<bench-lan-ip>:3000/login` (Caddy proxies `/api` → central). With `OPENFDD_JWT_SECRET` + `OPENFDD_ADMIN_PASSWORD` in `.env`, login as `admin` with that password.

**Also retest after stack P0s (#502):** central no longer crash-loops on `/openapi.json`; MQTT telemetry `value` non-null; MS/TP **5007** uses `add_routed_device`.

---

## Target build

| Item | Value |
|------|-------|
| **Minimum version** | **3.2.13** — PCAP Who-Is storm fix (skip 3.2.12 bench) |
| **Image** | `ghcr.io/bbartling/openfdd-edge-rust:nightly` |
| **What changed** | Poll never broadcasts Who-Is; registry address seed; commission-only poll on bridge; narrow discover range; PCAP script |
| **Last bench** | `802258a` @ 3.2.11 — **FAIL** PCAP (19 BVLC broadcast, network down); **do not retest 40fecf7** |
| **OT device** | MSTP **5007** @ router `192.168.204.200:47808`, net **2000**, MAC **`[7]`** — OA-T **AI:1173** ~71°F |

---

## PHASE 0 — PCAP gate (mandatory before other gates)

After deploy, with stack running 5 minutes:

```bash
OPENFDD_EDGE_SHA="$(curl -s http://127.0.0.1:8080/api/health | jq -r '.git_sha[0:7]')"
./scripts/bench/run_bacnet_pcap_capture.sh 300
```

**PASS criteria** (vs vibe16 baseline): **0 TX to `192.168.204.255`**, peak pkt/s **≤15**, router `.200` **≤10/min** per device at 60s poll.

**FAIL → stop stack immediately**, comment #429 + #464, do not run 30m soak.

---

## PHASE 1 — Wait for `:nightly` (repeat every 30 min until green)

```bash
REPO=bbartling/open-fdd
MIN_VERSION=3.2.13

echo "=== master HEAD ==="
gh api repos/$REPO/commits/master --jq '{sha: .sha[0:7], msg: .commit.message[0:80]}'

echo "=== GHCR publish (gate) ==="
gh run list --repo "$REPO" --workflow "Publish Rust edge to GHCR" --branch master --limit 3 \
  --json databaseId,status,conclusion,headSha,createdAt \
  | jq '.[] | {run: .databaseId, status, conclusion, sha: .headSha[0:7], created: .createdAt}'
```

**Proceed to Phase 2 only when:** GHCR `success` on commit containing **3.2.13** edge version.

**Do not** run `openfdd_rust_site_update.sh` until GHCR is green.

---

## PHASE 2 — Preflight + deploy (GHCR pull only)

Set in bench `workspace/data.env.local` or override:

```bash
OPENFDD_BACNET_COMMISSION_OWNS_POLL=1
```

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Kill vibe16 — steals UDP :47808
pkill -f 'target/release/bacnet_app' || true
pkill -f 'openfdd-bacnet-feather-concept' || true
pgrep -af bacnet_app || echo "OK: no stray bacnet_app"

chmod 644 workspace/auth.env.local

# Sync scripts/docs (bench is not git — use product handoff/rsync if available)
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_src_sync_for_test.sh 2>/dev/null || true

# Deploy
REQUIRE_BACKUP=0 ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh

HEALTH=$(curl -s http://127.0.0.1:8080/api/health)
echo "$HEALTH" | jq '{version, git_sha, image_tag: .image_tag // "nightly", ok}'
DEPLOY_SHA=$(echo "$HEALTH" | jq -r '.git_sha // .git_sha_short // empty' | cut -c1-7)
```

**Abort** if `DEPLOY_SHA` is not `10c5aa5` (or a later master SHA) — nightly not refreshed. `version` must be **3.2.13**.

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
# Never print TOKEN on GitHub
```

Start poll daemon:

```bash
./scripts/bench/openfdd_bacnet_poll_daemon.sh stop 2>/dev/null || true
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/bench/openfdd_bacnet_poll_daemon.sh start
./scripts/bench/openfdd_bacnet_poll_daemon.sh status
```

---

## PHASE 3 — GO NUTS gate matrix (run in order)

Save artifacts under `workspace/logs/nightly_go_nuts_${STAMP}/`.

### G0 — Stack health

```bash
curl -s http://127.0.0.1:8080/api/health | jq .
docker compose ps
./scripts/openfdd_docker_health_audit.sh 2>/dev/null || true
```

### G1 — P0 MSTP 5007 ([#464](https://github.com/bbartling/open-fdd/issues/464), [#465](https://github.com/bbartling/open-fdd/issues/465))

**This is the sign-off blocker.**

```bash
# Who-Is 5007 on BRIDGE :8080 (not :9091)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":5007,"high":5007}' | tee /tmp/whois_5007.json | jq .

# Read OA-T
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/read \
  -d '{"point_id":"bacnet:5007:analog-input:1173"}' | tee /tmp/read_5007_oat.json | jq .

# Point discovery
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/point-discovery \
  -d '{"device_instance":5007}' | jq '{ok, points: (.points|length)?}'

# Routing in registry
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | \
  jq '[..|objects|select(.device_instance?==5007)]|.[0]|{device_instance,address,mstp_network,mstp_mac,source}'

# Poll samples must rise for 5007
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
sleep 90
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .

# Historian pivot contains 5007
grep -c '"device_instance":5007' workspace/data/pivot/telemetry_pivot.jsonl 2>/dev/null || \
  grep -c '5007' workspace/data/pivot/telemetry_pivot.jsonl 2>/dev/null || echo "check pivot manually"
```

| Pass criteria |
|---------------|
| Who-Is JSON includes **5007** @ `192.168.204.200` |
| Read OA-T **~71°F** (not `unknown-object`) |
| `driver_tree` has `mstp_network` / `mstp_mac` |
| Poll **samples ↑** over 90s |
| Pivot rows for 5007 appear |

### G2 — P0 FDD profile ([#466](https://github.com/bbartling/open-fdd/issues/466))

**No `site.local.toml` workaround.**

```bash
mv workspace/config/site.local.toml workspace/config/site.local.toml.bak.$(date +%s) 2>/dev/null || true

export OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_validation_profile.local.toml
export OPENFDD_INTEGRATOR_PASSWORD="$INTEGRATOR_PW"
export OPENFDD_AGENT_PASSWORD="$(grep '^OFDD_AGENT_PASSWORD=' workspace/auth.env.local | cut -d= -f2- 2>/dev/null || \
  grep '^agent:' workspace/bootstrap_credentials.once.txt 2>/dev/null | cut -d' ' -f2-)"

BENCH_SMOKE_SHORT_FDD=1 ./scripts/smoke_live_fdd_validation.sh
```

Pass: single FDD cycle completes — **no** `smoke profile missing device_instance`.

### G3 — P0 regressions (closed @ 802258a — reconfirm)

```bash
docker logs openfdd-bridge 2>&1 | grep -E 'panic|BACnet server' | tail -15

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":599990,"high":600000}' | jq .

find workspace/data/pivot -name 'telemetry_pivot.jsonl' -printf '%T+ %p\n' 2>/dev/null
ls -lt workspace/data/feather_store/bacnet/*/*/*.feather 2>/dev/null | head -5
```

### G4 — Drivers matrix ([#433](https://github.com/bbartling/open-fdd/issues/433), [#429](https://github.com/bbartling/open-fdd/issues/429))

```bash
./scripts/openfdd_modbus_smoke.sh 2>/dev/null || true
./scripts/openfdd_haystack_smoke.sh 2>/dev/null || true
./scripts/openfdd_drivers_validate.sh || true

curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/test | jq '{ok,message}'
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/poll-once | jq '{ok,records: (.records|length)?}'

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/modbus/poll/status | jq .
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/validate | jq .
```

### G5 — P1 fixes (spot check)

| Issue | Command | Pass |
|-------|---------|------|
| **#467** EMFILE | 50× `POST /api/bacnet/read` on commission `:9091`; `docker logs openfdd-commission 2>&1 \| grep EMFILE` → empty | no EMFILE |
| **#469** auth 644 | `./scripts/openfdd_auth_init.sh --rotate --role agent --show-secrets --restart` (lab); `/health` OK without manual chmod | bridge healthy |
| **#470** bench scripts | `test -x scripts/bench/openfdd_bacnet_poll_daemon.sh && echo OK` | scripts present |

### G6 — 30m rigorous FDD soak (only if G1 + G2 PASS)

**Use device 5007 in validation profile — not 3456790 workaround.**

Ensure `local_validation_profile.local.toml` (or env) sets `device_instance = 5007` and BACnet point roles for 5007.

```bash
export OPENFDD_HAYSTACK_BASE='https://192.168.204.11/haystack'
export OPENFDD_HAYSTACK_USER='open_fdd'
export OPENFDD_HAYSTACK_PASS='...'   # from bench secrets — never commit
export OPENFDD_MODBUS_HOST='192.168.204.14'

# If orchestrator exists from prior bench run:
./workspace/logs/rigorous_fdd_30m_runner.sh 2>/dev/null || \
  BENCH_SMOKE_DURATION_MINUTES=30 OPENFDD_SMOKE_LIVE_FDD=1 OPENFDD_SMOKE_NO_DEMO_PASS=1 \
  OPENFDD_SMOKE_VALIDATE_MODBUS=1 OPENFDD_SMOKE_REQUIRE_MODBUS=1 \
  ./scripts/smoke_live_fdd_validation.sh
```

Pass: `live_fdd_pass: true`, `interval_failures: 0`, `demo_only: false`, `data_source=bacnet:live` for **5007**.

### G7 — Short soak (if no time for G6)

```bash
OPENFDD_SOAK_MINUTES=10 ./scripts/bench/openfdd_stores_fdd_soak.sh
```

---

## PHASE 4 — GitHub evidence (post everything)

| Issue | Post when |
|-------|-----------|
| **[#429](https://github.com/bbartling/open-fdd/issues/429)** | **Always** — full report below |
| **#464, #466** | G1/G2 result — **close if PASS** with JSON snippets |
| **#465, #467, #469** | G5 result |
| **#433, #431** | G4 validate JSON |
| **#429 sign-off** | **YES** only if G1 + G2 + G6 pass |

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
REPORT=/tmp/edge-go-nuts-${STAMP}.md
# fill template below → gh issue comment 429 --repo bbartling/open-fdd --body-file "$REPORT"
```

### Report template (#429)

```markdown
## GO NUTS retest — nightly @ `<DEPLOY_SHA>` (3.2.13)

**GHCR deploy:** `openfdd_rust_site_update.sh` · **Health:** (version / git_sha)
**LAST_TESTED_SHA:** `<DEPLOY_SHA>`

### Gate matrix

| Gate | Issue | Result | Evidence |
|------|-------|--------|----------|
| Who-Is 5007 bridge | #464/#465 | PASS/FAIL | /tmp/whois_5007.json |
| Read OA-T 5007 | #464 | PASS/FAIL | /tmp/read_5007_oat.json |
| Poll + pivot 5007 | #464 | PASS/FAIL | poll/status ×2, pivot grep |
| FDD no site.local.toml | #466 | PASS/FAIL | smoke output |
| Server no panic | regressed | PASS/FAIL | bridge log |
| Haystack + Modbus | #433 | PASS/FAIL | test/poll-once |
| 30m rigorous FDD 5007 | #429 | PASS/FAIL/SKIP | summary.jsonl |

### Still not working

1. …

### Sign-off

**Product sign-off: NO** / **YES**
**FDD pipeline sign-off: NO** / **YES**

**Artifacts:** `workspace/logs/nightly_go_nuts_*` (no secrets)
```

---

## Sign-off rubric (#429)

| Area | YES requires |
|------|----------------|
| **Product** | G1 5007 bridge Who-Is + read + poll + pivot |
| **FDD pipeline** | G2 profile fix + G6 30m soak with **5007**, zero interval failures |
| **Drivers** | Modbus + Haystack live (G4) |

If G1 or G2 **FAIL**: post product handoff on #429 — WSL fixes + new nightly; do **not** claim YES.

---

## Rules

- **GHCR pull only** — never `docker build` / `cargo build` on bench.
- **Never** push git from `/home/ben/open-fdd` (not a git repo).
- Preflight: kill vibe16; `chmod 644 workspace/auth.env.local`.
- Never `docker compose down -v` · never delete `workspace/` · never print tokens/passwords on GitHub.
- Vibe16 reference if 5007 fails but OT is up: `/home/ben/py-bacnet-stacks-playground/.../openfdd-bacnet-feather-concept`

---

*Created 2026-07-07 for 3.2.13 @ `10c5aa5` PCAP Who-Is storm fix — GHCR `:nightly` green 2026-07-08. Paste now.*
