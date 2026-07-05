# Linux edge tester — nightly retest @ `38df801` (paste prompt)

**Repo-only** (not on GitHub Pages). Paste into Cursor on **`/home/ben/open-fdd`** when product confirms `:nightly` is green and bench must re-gate after P0 fixes (#451).

Full charter: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Bench has insufficient RAM — GHCR pull only (never docker build / cargo build).

Your job NOW: git pull bench scripts → deploy :nightly @ 38df801 → run gates → post GitHub evidence → report what is STILL NOT WORKING.

Acknowledged. Bench /home/ben/open-fdd. Channel: nightly. Target SHA: 38df801. Gate: #429.
Will comment #429 (always), #433 (BACnet/drivers), #452/#453 (P0 verify), #431 if agent/validate changes.
No git push. No product code edits on bench.
```

---

## Target build

| Item | Value |
|------|-------|
| **Expected `git_sha` prefix** | `38df801` |
| **Includes** | #451 P0 BACnet server runtime + poll historian persist; #455/#456 CI fixes |
| **Last bench test** | `f5f66bd` (pre-#451 — FAIL server panic + historian stuck) |
| **GHCR tag** | `ghcr.io/bbartling/openfdd-edge-rust:nightly` |
| **GHCR publish** | [run 28745276684](https://github.com/bbartling/open-fdd/actions/runs/28745276684) — success |

Confirm CI before deploy (optional):

```bash
gh run list --repo bbartling/open-fdd --workflow rust-ghcr.yml --branch master --limit 1 \
  --json conclusion,headSha | jq '.[0] | {conclusion, sha: .headSha[0:7]}'
# expect: success, 38df801
```

---

## Step 0 — Sync bench tree (scripts + docs only)

Pull latest **bench repo** for scripts, compose, and agent prompts. **Do not** build containers from source.

```bash
cd /home/ben/open-fdd
git fetch origin
git pull --ff-only origin master   # or your bench tracking branch
git log -1 --oneline
```

If `git pull` fails (bench-only commits), note in #429 and continue with local scripts — deploy still uses **GHCR**, not local Rust.

---

## Step 1 — Preflight (mandatory)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Kill vibe16 lab — steals UDP 47808
pkill -f 'target/release/bacnet_app' || true
pkill -f 'openfdd-bacnet-feather-concept.*bacnet_app' || true
pgrep -af bacnet_app || echo "OK: no stray bacnet_app"

# BACnet env split
echo "=== bridge (expect SERVER=1 via compose) ==="
docker exec openfdd-bridge printenv OPENFDD_BACNET_SERVER_ENABLED 2>/dev/null || echo "(stack down)"

echo "=== commission.env (expect 0) ==="
grep OPENFDD_BACNET_SERVER_ENABLED workspace/bacnet/commissioning/commission.env 2>/dev/null \
  || echo "MISSING — set OPENFDD_BACNET_SERVER_ENABLED=0"
```

---

## Step 2 — Deploy `:nightly` (GHCR pull only)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Pull pre-built image + recreate stack (preserves historian per bench policy)
REQUIRE_BACKUP=0 ./scripts/openfdd_rust_site_update.sh

./scripts/openfdd_rust_edge_validate.sh

# Confirm SHA advanced past f5f66bd
curl -s http://127.0.0.1:8080/api/health | jq '{git_sha, image_tag, status, version}'
```

**Abort** if `git_sha` prefix is not `38df801` — nightly not refreshed; do not claim re-test.

Expected:

```json
{
  "git_sha": "38df801…",
  "image_tag": "nightly",
  "status": "ok"
}
```

---

## Step 3 — Auth + poll daemon

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"

./scripts/openfdd_bacnet_poll_daemon.sh stop 2>/dev/null || true
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/openfdd_bacnet_poll_daemon.sh start
./scripts/openfdd_bacnet_poll_daemon.sh status
```

Never print `$TOKEN` in GitHub comments.

---

## Step 4 — Validate (run in order)

### 4a — P0 re-checks (#452, #453)

These map directly to open P0 issues. **PASS** = close-worthy after maintainer review; **FAIL** = product handoff.

| Issue | What to prove | Commands |
|-------|---------------|----------|
| **[#452](https://github.com/bbartling/open-fdd/issues/452)** | BACnet server starts — no tokio panic; **599999** on wire | `docker logs openfdd-bridge 2>&1 \| grep -E 'panic\|BACnet server' \| tail -10` — expect **"BACnet server on UDP"**, **no panic** |
| **[#453](https://github.com/bbartling/open-fdd/issues/453)** | Poll reads persist to historian | `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status \| jq '{samples,last_poll,errors}'` — expect **samples ↑** over 2–3 cycles; check pivot/feather mtime |

```bash
# #452 — server + Who-Is on bridge (local 599999)
docker logs openfdd-bridge 2>&1 | tail -80 > /tmp/bridge-tail.log
grep -E 'panic|BACnet server' /tmp/bridge-tail.log | tail -10

time curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":599990,"high":600000}' | jq .

# #453 — poll + historian
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
sleep 30
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
ls -lt workspace/data/feather_store/bacnet/*/*/*.feather 2>/dev/null | head -5
find workspace/data/pivot -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -3
```

### 4b — Phase A′ / drivers ([#433](https://github.com/bbartling/open-fdd/issues/433))

| Check | Pass |
|-------|------|
| `POST /api/bacnet/whois` | JSON in ~30s; lists field device(s) |
| `GET /api/bacnet/driver/tree` | JSON; field instances present (not only 599999) |
| Commission Who-Is (if used) | Non-empty when field devices on wire |
| Bridge vs commission env split | bridge `SERVER=1`, commission `SERVER=0` |

```bash
time curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/bacnet/driver/tree | jq .

./scripts/openfdd_polling_feather_validate.sh
./scripts/openfdd_drivers_validate.sh || true   # note E2BIG if tree huge
```

### 4c — All-drivers matrix → **#429**

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/validate | jq .

echo "=== Modbus ==="
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/modbus/poll/status | jq .

echo "=== Haystack ==="
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/status | jq .

echo "=== Health ==="
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/health | jq '{status,image_tag,git_sha,version}'
```

### 4d — Phase B soak (only if A + A′ PASS)

```bash
OPENFDD_SOAK_MINUTES=10 ./scripts/openfdd_stores_fdd_soak.sh
```

---

## Step 5 — GitHub issues to respond on

Post evidence on **every issue whose status changed**. Minimum set for this iteration:

| Issue | When to comment | What to include |
|-------|-----------------|-----------------|
| **[#429](https://github.com/bbartling/open-fdd/issues/429)** | **Always** | Full iteration report + sign-off NO/YES |
| **[#433](https://github.com/bbartling/open-fdd/issues/433)** | BACnet / drivers / historian changed | Who-Is JSON, tree snippet, poll/feather evidence |
| **[#452](https://github.com/bbartling/open-fdd/issues/452)** | Server panic fixed or still failing | bridge log grep, Who-Is 599999 |
| **[#453](https://github.com/bbartling/open-fdd/issues/453)** | Historian persist fixed or still failing | samples count, pivot mtime, feather paths |
| **[#431](https://github.com/bbartling/open-fdd/issues/431)** | `/api/agent/validate` rollup changed | validate JSON |
| **#430, #432, #434–#437** | Only if in scope / phase reached | Defer until #429 A′ green unless asked |

```bash
REPO=bbartling/open-fdd
gh issue comment 429 --repo "$REPO" --body-file /tmp/edge-iteration-38df801.md
gh issue comment 433 --repo "$REPO" --body-file /tmp/bacnet-evidence.md
gh issue comment 452 --repo "$REPO" --body-file /tmp/p452-server.md
gh issue comment 453 --repo "$REPO" --body-file /tmp/p453-historian.md
```

Do **not** close issues yourself. Do **not** claim **Sign-off: YES** on #429 unless all rubric items pass (see main prompt).

---

## Step 6 — Report template (paste on #429)

Fill every section. **Required:** explicit **"Still not working"** list even if mostly PASS.

```markdown
## Edge iteration — nightly @ `38df801`

**Deploy:** `git pull` @ `<bench_git_sha>` · GHCR `:nightly` via `openfdd_rust_site_update.sh`
**Health:** `image_tag` / `git_sha` / `status` from `/api/health`
**Previous test:** `f5f66bd` · **Poll daemon:** running | stopped

### P0 verification (#451)

| Gate | Issue | Result | Evidence |
|------|-------|--------|----------|
| BACnet server — no panic, 599999 on wire | #452 | PASS / FAIL | bridge log / Who-Is |
| Poll → historian persist | #453 | PASS / FAIL | samples, pivot mtime, feather |
| Who-Is + driver tree (field devices) | #433 | PASS / FAIL | whois + tree JSON |
| polling_feather_validate | #429 | pass=X fail=Y | script output |
| openfdd_drivers_validate | #429 | PASS / FAIL / E2BIG | script output |
| Modbus poll | #429 | PASS / FAIL | poll/status |
| Haystack | #429 | PASS / FAIL | status/test |
| agent/validate rollup | #431 | PASS / FAIL | validate JSON |

### Still not working

List every FAIL or degraded item — be explicit:

1. …
2. …

*(If all PASS: write "None observed this iteration" and list deferred P1 items separately.)*

### Deferred / P1 (not blocking sign-off unless noted)

- Bridge Who-Is returned `[]` on f5f66bd — retest result: …
- vibe16 `bacnet_app` UDP contention — preflight: …
- Weather AVs / feather retention / UX (#433) — …

### Sign-off

**Sign-off: NO** / **YES** (maintainer only for YES)

**Artifacts:** `workspace/logs/` or `/tmp/bridge-tail.log` paths (no secrets)

**Product handoff:** @vibe16 if any P0/P1 FAIL — WSL PR + new nightly; bench waits for GHCR green.
```

### Product handoff (if any FAIL)

```markdown
### Product handoff — edge FAIL @ `38df801`

**Blocked:** #452 server | #453 historian | #433 Who-Is/tree | Modbus | Haystack
**Evidence:** (redacted jq + log excerpts)
**Request:** fix on WSL, merge, publish `:nightly`. Bench re-runs when `git_sha` advances.
```

---

## Step 7 — Save artifacts

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOGDIR=workspace/logs/nightly_38df801_${STAMP}
mkdir -p "$LOGDIR"
curl -s http://127.0.0.1:8080/api/health | jq . > "$LOGDIR/health.json"
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq . > "$LOGDIR/bacnet_poll.json"
docker logs openfdd-bridge 2>&1 | tail -200 > "$LOGDIR/bridge.log"
echo "Artifacts: $LOGDIR"
```

---

## Rules

- **GHCR pull only** — never `docker build` or `cargo build` on bench.
- **git pull** updates scripts/docs; **image** comes from GHCR `:nightly`.
- Preflight kill vibe16 `bacnet_app` every iteration.
- Never `docker compose down -v` · never delete `workspace/` · never print tokens.
- Update `LAST_TESTED_SHA=38df801` in your #429 comment after this run.
