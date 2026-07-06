# Linux edge tester — nightly retest @ `dfde570` (paste prompt)

**Repo-only** (not on GitHub Pages). Paste into Cursor on **`/home/ben/open-fdd`** when product confirms `:nightly` is green on **`dfde570`** (or later master SHA that includes **3.2.11** edge).

Full charter: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md) · GH Actions watch: [linux-edge-tester-gh-actions-watch-prompt.md](./linux-edge-tester-gh-actions-watch-prompt.md)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Bench has insufficient RAM — GHCR pull only (never docker build / cargo build).

Your job NOW: sync bench scripts → deploy :nightly @ dfde570 (3.2.11) → run gates → post GitHub evidence → report what is STILL NOT WORKING.

Acknowledged. Bench /home/ben/open-fdd. Channel: nightly. Target SHA: dfde570 (3.2.11). Gate: #429.
Will comment #429 (always), #433 (drivers/BACnet/historian/Haystack), #452/#453 (P0 verify).
No git push. No product code edits on bench.
```

---

## Target build

| Item | Value |
|------|-------|
| **Expected `git_sha` prefix** | `dfde570` (minimum) — **3.2.11** via [#461](https://github.com/bbartling/open-fdd/pull/461) |
| **Includes** | Haystack Basic-auth `text/zinc` POST (#461); BACnet server dedicated thread; pivot append error logging; headless CSV batch (no `/csv` UI) |
| **Last bench test** | `d1483d0` @ 3.2.10 — partial: samples ↑, Who-Is 599999, **server panic**, **pivot frozen Jul 3**, Haystack **HTTP 415** on poll-once |
| **GHCR tag** | `ghcr.io/bbartling/openfdd-edge-rust:nightly` |
| **Vibe16 lab** | [openfdd-bacnet-feather-concept](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_16/openfdd-bacnet-feather-concept) — kill before BACnet tests |

Confirm CI before deploy:

```bash
gh run list --repo bbartling/open-fdd --workflow rust-ghcr.yml --branch master --limit 3 \
  --json conclusion,headSha,status | jq '.[] | select(.headSha|startswith("dfde570") or startswith("802258a7")) | {conclusion, sha: .headSha[0:7], status}'
# expect: conclusion success on dfde570 or later master (802258a7 docs-only is OK — same edge binary)
```

**Abort** deploy if `/api/health` `git_sha` prefix is still `d1483d0` or older — nightly not refreshed.

---

## Open issues — still legit @ 2026-07-06

| Issue | Status | Retest focus |
|-------|--------|--------------|
| **[#429](https://github.com/bbartling/open-fdd/issues/429)** | OPEN — sign-off **NO** | Full iteration report every run |
| **[#452](https://github.com/bbartling/open-fdd/issues/452)** | OPEN — P0 | Bridge logs: **zero panic**; Who-Is → 599999; server on UDP :47808 |
| **[#453](https://github.com/bbartling/open-fdd/issues/453)** | OPEN — P0 partial | **samples ↑** (was fixed @ d1483d0); **`telemetry_pivot.jsonl` mtime must advance** |
| **[#433](https://github.com/bbartling/open-fdd/issues/433)** | OPEN — P1 | Haystack poll-once/read (was HTTP 415); bridge field Who-Is; driver tree |
| **#430–#437** | OPEN — 3.2.8 backlog | Defer unless in scope; not blocking #429 A′ |

Do **not** close P0 issues yourself. Comment PASS/FAIL with evidence.

---

## Step 0 — Sync bench tree (scripts + docs only)

```bash
cd /home/ben/open-fdd
git fetch origin
git pull --ff-only origin master 2>/dev/null || echo "Note: bench may not be a git repo — scripts from product handoff OK"
git log -1 --oneline 2>/dev/null || true
```

Deploy uses **GHCR**, not local Rust.

---

## Step 1 — Preflight (mandatory)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Kill vibe16 — steals UDP :47808
pkill -f 'target/release/bacnet_app' || true
pkill -f 'openfdd-bacnet-feather-concept' || true
pgrep -af bacnet_app || echo "OK: no stray bacnet_app"

# Auth readable by container uid 10001 (3.2.10+)
chmod 644 workspace/auth.env.local 2>/dev/null || true

# BACnet env split
docker exec openfdd-bridge printenv OPENFDD_BACNET_SERVER_ENABLED 2>/dev/null || echo "(stack down)"
grep OPENFDD_BACNET_SERVER_ENABLED workspace/bacnet/commissioning/commission.env 2>/dev/null || true
```

---

## Step 2 — Deploy `:nightly` (GHCR pull only)

```bash
REQUIRE_BACKUP=0 ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
curl -s http://127.0.0.1:8080/api/health | jq '{git_sha, image_tag, status, version}'
```

Expected: `version` **3.2.11**, `git_sha` prefix **`dfde570`** or later, `image_tag` **nightly**.

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

| Issue | What to prove |
|-------|---------------|
| **#452** | No tokio panic in bridge logs; **599999** in Who-Is; `/api/bacnet/server/points` OK |
| **#453** | Poll **samples ↑**; **`telemetry_pivot.jsonl` mtime advances** after 90s poll; feather shards grow |

```bash
docker logs openfdd-bridge 2>&1 | grep -E 'panic|BACnet server' | tail -10

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":599990,"high":600000}' | jq .

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
sleep 90
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .

find workspace/data/pivot -name 'telemetry_pivot.jsonl' -printf '%T+ %p\n' 2>/dev/null
ls -lt workspace/data/feather_store/bacnet/*/*/*.feather 2>/dev/null | head -5
```

### 4b — Haystack (#433) — **new @ 3.2.11**

Niagara nHaystack was **HTTP 415** on `read`/`poll-once` @ d1483d0. #461 sends **`text/zinc`** for Basic auth POST.

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/status | jq .
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/test | jq '{ok,message}'
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/poll-once | jq '{ok,message,records: (.records|length)?}'
```

### 4c — Drivers matrix → **#429**

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | jq '.devices|length?'

./scripts/openfdd_polling_feather_validate.sh
./scripts/openfdd_drivers_validate.sh || true
./scripts/openfdd_docker_health_audit.sh || true

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/modbus/poll/status | jq '{samples,last_poll}'
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/validate | jq .
```

### 4d — Phase B soak (only if A + A′ PASS)

```bash
OPENFDD_SOAK_MINUTES=10 ./scripts/openfdd_stores_fdd_soak.sh
```

---

## Step 5 — GitHub issues to respond on

| Issue | When |
|-------|------|
| **#429** | **Always** — full report + sign-off NO/YES |
| **#452, #453** | P0 server + pivot evidence |
| **#433** | Haystack poll-once, Who-Is/tree, historian |
| **#431** | If `/api/agent/validate` rollup changed |

```bash
gh issue comment 429 --repo bbartling/open-fdd --body-file /tmp/edge-iteration-dfde570.md
```

Do **not** claim **Sign-off: YES** unless all rubric items pass.

---

## Step 6 — Report template (#429)

```markdown
## Edge iteration — nightly @ `dfde570` (3.2.11)

**Deploy:** GHCR `:nightly` · **Health:** (git_sha / version / status)
**Previous test:** `d1483d0` @ 3.2.10 · **Poll daemon:** running | stopped

### P0 / drivers

| Gate | Issue | Result | Evidence |
|------|-------|--------|----------|
| BACnet server — no panic | #452 | PASS/FAIL | bridge log |
| Who-Is 599999 | #452 | PASS/FAIL | whois JSON |
| Poll samples ↑ | #453 | PASS/FAIL | poll/status ×2 |
| Pivot JSONL mtime advances | #453 | PASS/FAIL | find mtime |
| Haystack poll-once | #433 | PASS/FAIL | was 415 @ d1483d0 |
| Haystack test/connection | #433 | PASS/FAIL | test JSON |
| polling_feather_validate | #429 | pass=X fail=Y | script |
| Modbus samples | #429 | PASS/FAIL | poll/status |

### Still not working

1. …

### Sign-off

**Sign-off: NO** / **YES**

**Artifacts:** `workspace/logs/nightly_retest_*` (no secrets)
```

---

## Step 7 — Artifacts

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOGDIR=workspace/logs/nightly_retest_${STAMP}
mkdir -p "$LOGDIR"
curl -s http://127.0.0.1:8080/api/health | jq . > "$LOGDIR/health.json"
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq . > "$LOGDIR/bacnet_poll.json"
docker logs openfdd-bridge 2>&1 | tail -200 > "$LOGDIR/bridge.log"
echo "Artifacts: $LOGDIR"
```

---

## Rules

- **GHCR pull only** — never `docker build` or `cargo build` on bench.
- Preflight: kill vibe16 `bacnet_app`; `chmod 644 workspace/auth.env.local`.
- Never `docker compose down -v` · never delete `workspace/` · never print tokens.
- Record `LAST_TESTED_SHA=dfde570` in #429 comment after deploy confirms health SHA.
