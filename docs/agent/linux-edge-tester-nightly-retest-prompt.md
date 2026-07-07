# Linux edge tester — nightly retest @ `40fecf7` (paste prompt)

**Repo-only** (not on GitHub Pages). Paste into Cursor on **`/home/ben/open-fdd`** when product confirms `:nightly` is green on **`40fecf7`** (or later master SHA that includes **3.2.12** edge).

Full charter: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md) · GH Actions watch: [linux-edge-tester-gh-actions-watch-prompt.md](./linux-edge-tester-gh-actions-watch-prompt.md) · Issue index: [WSL_CURSOR_AGENT_ISSUES.md](./WSL_CURSOR_AGENT_ISSUES.md)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Bench has insufficient RAM — GHCR pull only (never docker build / cargo build).

Your job NOW: sync bench scripts → deploy :nightly @ 40fecf7 (3.2.12) → run gates → post GitHub evidence → report what is STILL NOT WORKING.

Acknowledged. Bench /home/ben/open-fdd. Channel: nightly. Target SHA: 40fecf7 (3.2.12). Gate: #429.
Will comment #429 (always), #464/#466 (5007 + FDD profile), #433 (drivers/Haystack), #465–#470 as applicable.
No git push. No product code edits on bench.
```

---

## Target build

| Item | Value |
|------|-------|
| **Expected `git_sha` prefix** | `40fecf7` — **3.2.12** via [#472](https://github.com/bbartling/open-fdd/pull/472) |
| **Includes** | MSTP routing persist + `read_property_routed`; FDD `OPENFDD_VALIDATION_PROFILE`; bridge→commission BACnet proxy; persistent BACnet client; auth 644; `scripts/bench/` |
| **Last bench test** | `802258a` @ 3.2.11 — FDD pipeline **PASS** (30m soak); **5007 MSTP FAIL** on bridge; FDD needed manual `site.local.toml` (#466) |
| **GHCR tag** | `ghcr.io/bbartling/openfdd-edge-rust:nightly` |
| **Vibe16 lab** | Kill before BACnet tests — steals UDP :47808 |

Confirm CI before deploy:

```bash
gh run list --repo bbartling/open-fdd --workflow rust-ghcr.yml --branch master --limit 1 \
  --json conclusion,headSha,status,databaseId | jq '.[0] | {conclusion, sha: .headSha[0:7], status, run: .databaseId}'
# expect: conclusion success, sha 40fecf7
```

**Abort** deploy if `/api/health` `git_sha` prefix is before `40fecf7` — nightly not refreshed.

---

## Open issues — retest focus @ 2026-07-07

| Issue | Status | Retest focus |
|-------|--------|--------------|
| **[#429](https://github.com/bbartling/open-fdd/issues/429)** | OPEN — sign-off **NO** | Full iteration; **YES** only when 5007 + FDD profile pass |
| **[#464](https://github.com/bbartling/open-fdd/issues/464)** | Fixed in 3.2.12 — verify | Who-Is/read/poll **device 5007** on bridge `:8080` |
| **[#466](https://github.com/bbartling/open-fdd/issues/466)** | Fixed in 3.2.12 — verify | FDD cycle with **only** `OPENFDD_VALIDATION_PROFILE` (no `site.local.toml`) |
| **[#465](https://github.com/bbartling/open-fdd/issues/465)** | Fixed in 3.2.12 — verify | Bridge Who-Is 5007 via commission proxy |
| **[#467](https://github.com/bbartling/open-fdd/issues/467)** | Fixed in 3.2.12 — verify | 50× read — no EMFILE in commission logs |
| **[#469](https://github.com/bbartling/open-fdd/issues/469)** | Fixed in 3.2.12 — verify | Auth rotate + restart without manual chmod |
| **[#470](https://github.com/bbartling/open-fdd/issues/470)** | Fixed in 3.2.12 — verify | `scripts/bench/openfdd_bacnet_poll_daemon.sh` exists after sync |
| **[#452](https://github.com/bbartling/open-fdd/issues/452)** | **PASS** @ 802258a | Reconfirm no panic + 599999 |
| **[#453](https://github.com/bbartling/open-fdd/issues/453)** | **PASS** @ 802258a (BIP) | Reconfirm samples ↑ + pivot growth |
| **[#433](https://github.com/bbartling/open-fdd/issues/433)** | OPEN — P1 | Haystack poll-once/read; driver tree UX |

Do **not** close issues yourself unless maintainer confirms bench PASS.

---

## Step 0 — Sync bench tree (scripts + docs only)

```bash
cd /home/ben/open-fdd
# If bench tracks product scripts via rsync:
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_src_sync_for_test.sh 2>/dev/null || true
git fetch origin 2>/dev/null; git pull --ff-only origin master 2>/dev/null || true
```

Deploy uses **GHCR**, not local Rust.

---

## Step 1 — Preflight (mandatory)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

pkill -f 'target/release/bacnet_app' || true
pkill -f 'openfdd-bacnet-feather-concept' || true
pgrep -af bacnet_app || echo "OK: no stray bacnet_app"

chmod 644 workspace/auth.env.local 2>/dev/null || true

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

Expected: `version` **3.2.12**, `git_sha` prefix **`40fecf7`**, `image_tag` **nightly**.

---

## Step 3 — Auth + poll daemon

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"

./scripts/bench/openfdd_bacnet_poll_daemon.sh stop 2>/dev/null || \
  ./scripts/openfdd_bacnet_poll_daemon.sh stop 2>/dev/null || true
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/bench/openfdd_bacnet_poll_daemon.sh start 2>/dev/null || \
  OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/openfdd_bacnet_poll_daemon.sh start
```

Never print `$TOKEN` in GitHub comments.

---

## Step 4 — Validate (run in order)

### 4a — P0 MSTP 5007 (#464, #465)

Router `192.168.204.200:47808`, MSTP net **2000**, MAC **`[7]`**.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":5007,"high":5007}' | jq .

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/read \
  -d '{"point_id":"bacnet:5007:analog-input:1173"}' | jq .

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
sleep 90
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | \
  jq '[..|objects|select(.device_instance?==5007)]|.[0]|{device_instance,mstp_network,mstp_mac,address}'
```

**PASS:** Who-Is includes 5007 @ `.200`; OA-T ~71°F; poll samples ↑ for 5007 points; `driver_tree.json` has routing fields.

### 4b — P0 FDD profile (#466)

Remove workaround if present, then single FDD cycle:

```bash
mv workspace/config/site.local.toml workspace/config/site.local.toml.bak 2>/dev/null || true

export OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_validation_profile.local.toml
export OPENFDD_INTEGRATOR_PASSWORD="$INTEGRATOR_PW"
BENCH_SMOKE_SHORT_FDD=1 ./scripts/smoke_live_fdd_validation.sh
```

**PASS:** FDD cycle completes without `smoke profile missing device_instance`.

### 4c — P0 regression (#452, #453)

```bash
docker logs openfdd-bridge 2>&1 | grep -E 'panic|BACnet server' | tail -10

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois \
  -d '{"low":599990,"high":600000}' | jq .

find workspace/data/pivot -name 'telemetry_pivot.jsonl' -printf '%T+ %p\n' 2>/dev/null
```

### 4d — Haystack + drivers (#433)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/test | jq '{ok,message}'
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/poll-once | jq '{ok,records: (.records|length)?}'

./scripts/openfdd_drivers_validate.sh || true
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/validate | jq .
```

### 4e — Phase B soak (only if 4a–4d PASS)

```bash
OPENFDD_SOAK_MINUTES=10 ./scripts/bench/openfdd_stores_fdd_soak.sh 2>/dev/null || \
  OPENFDD_SOAK_MINUTES=10 ./scripts/openfdd_stores_fdd_soak.sh
```

For **30m rigorous FDD with device 5007** (sign-off gate): use `workspace/logs/rigorous_fdd_30m_runner.sh` after 4a+4b PASS.

---

## Step 5 — GitHub issues to respond on

| Issue | When |
|-------|------|
| **#429** | **Always** — full report + sign-off NO/YES |
| **#464, #466** | 5007 + FDD profile evidence |
| **#465–#470** | If retest confirms fix |
| **#433** | Haystack, drivers, historian |
| **#452, #453** | Regression reconfirm |

Do **not** claim **Sign-off: YES** on #429 until **5007 on bridge** + **FDD without site.local.toml** + 30m soak with 5007.

---

## Step 6 — Report template (#429)

```markdown
## Edge iteration — nightly @ `40fecf7` (3.2.12)

**Deploy:** GHCR `:nightly` · **Health:** (git_sha / version / status)
**Previous test:** `802258a` @ 3.2.11 · **Poll daemon:** running | stopped

### P0 gates

| Gate | Issue | Result | Evidence |
|------|-------|--------|----------|
| Who-Is 5007 on bridge | #464/#465 | PASS/FAIL | whois JSON |
| Read OA-T 5007 | #464 | PASS/FAIL | read JSON ~71°F |
| Poll samples 5007 | #464 | PASS/FAIL | poll/status ×2 |
| FDD without site.local.toml | #466 | PASS/FAIL | smoke script |
| Server no panic | #452 | PASS/FAIL | bridge log |
| Pivot growth | #453 | PASS/FAIL | pivot mtime |

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
- Record `LAST_TESTED_SHA=40fecf7` in #429 comment after deploy confirms health SHA.
