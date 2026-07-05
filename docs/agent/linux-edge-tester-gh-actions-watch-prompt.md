# Linux edge tester — GH Actions watch & proceed (paste prompt)

**Repo-only** (not on GitHub Pages). Paste into Cursor on **`/home/ben/open-fdd`** when product has merged PR(s) and you are waiting for `:nightly` before re-gating.

Full charter: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Your job NOW: watch GitHub Actions until :nightly is green, then deploy and re-run gates.

Acknowledged. Bench /home/ben/open-fdd. Channel: nightly. Gate: #429.
Will watch GH Actions, post on #429/#433, proceed only when nightly is published.
No git push. No product code edits on bench.
```

---

## What you are waiting for

Product merges land on **`master`** → CI runs → **`Publish Rust edge to GHCR`** pushes **`ghcr.io/bbartling/openfdd-edge-rust:nightly`**.

You proceed when **all** of these are true:

| Check | Required |
|-------|----------|
| Merged PR on master | Yes — note PR number + title |
| **Rust Edge CI** | `conclusion: success` on merge commit |
| **Publish Rust edge to GHCR** | `conclusion: success` on same merge commit |
| **Local `git_sha`** after deploy | Matches merge commit prefix (7 chars) |
| Last tested SHA | **Different** from new merge (do not re-test same image twice) |

Optional (informational only — does not block bench):

| Workflow | Use |
|----------|-----|
| Docs (GitHub Pages) | Cookbook/docs updated — not required for edge gates |
| Cookbook parity | Docs fixtures — not required for edge gates |
| AppSec / Security Guards | Must be green on PR; note if master red |

---

## Step 1 — Watch GitHub Actions (repeat every 10–15 min)

Requires **`gh`** authenticated on bench (`gh auth status`).

```bash
REPO=bbartling/open-fdd
LAST_TESTED_SHA="${LAST_TESTED_SHA:-f5f66bd}"   # set from your last #429 comment

echo "=== Last tested on bench: $LAST_TESTED_SHA ==="

# Latest master commit
gh api repos/$REPO/commits/master --jq '{sha: .sha[0:7], msg: .commit.message[0:72], date: .commit.committer.date}'

# GHCR publish (the gate that matters for :nightly)
gh run list --repo "$REPO" --workflow "Publish Rust edge to GHCR" --branch master --limit 3 \
  --json conclusion,status,headSha,displayTitle,createdAt,updatedAt,url \
  | jq '.[] | {status, conclusion, sha: .headSha[0:7], title: .displayTitle[0:60], url}'

# Rust CI on master
gh run list --repo "$REPO" --workflow "Rust Edge CI" --branch master --limit 2 \
  --json conclusion,status,headSha | jq '.[0] | {status, conclusion, sha: .headSha[0:7]}'

# Open PRs still in flight (product may merge more — wait for the one you care about)
gh pr list --repo "$REPO" --state open --limit 5
```

### Decision table

| GHCR publish | Rust CI | Action |
|--------------|---------|--------|
| `queued` / `in_progress` | any | **WAIT** — post “watching CI” on #429 if >30 min |
| `failure` | any | **STOP** — post FAIL on #429; tag product agent; do not deploy |
| `success` | `success` | **GO** → Step 2 if `headSha` ≠ `LAST_TESTED_SHA` |
| `success` | still running | **WAIT** for Rust CI |
| `success` | `failure` | **STOP** — post on #429; product must fix |

When **GO**, record:

```bash
NEW_SHA=$(gh api repos/$REPO/commits/master --jq -r '.sha[0:7]')
echo "Proceed with nightly @ $NEW_SHA"
```

---

## Step 2 — Confirm GHCR tag exists (before pull)

```bash
export OPENFDD_IMAGE_TAG=nightly
IMAGE=ghcr.io/bbartling/openfdd-edge-rust:nightly

docker manifest inspect "$IMAGE" >/dev/null && echo "GHCR :nightly OK" || echo "NOT PUBLISHED YET — wait"

# Optional: digest / created (no secrets)
docker pull "$IMAGE" 2>&1 | tail -3
```

---

## Step 3 — Preflight + deploy (mandatory every iteration)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Kill vibe16 lab — steals UDP 47808
pkill -f 'target/release/bacnet_app' || true
pkill -f 'openfdd-bacnet-feather-concept.*bacnet_app' || true
pgrep -af bacnet_app || echo "OK: no stray bacnet_app"

# Deploy
REQUIRE_BACKUP=0 ./scripts/openfdd_rust_site_update.sh
# or: ./scripts/openfdd_bench_pull_ghcr.sh && docker compose -f docker/compose.edge.rust.yml up -d --force-recreate

./scripts/openfdd_rust_edge_validate.sh

# Confirm SHA advanced
curl -s http://127.0.0.1:8080/api/health | jq '{git_sha, image_tag, version, status}'
```

**Abort deploy** if `git_sha` prefix still equals `LAST_TESTED_SHA` — nightly not refreshed yet.

---

## Step 4 — Run gates (orchestration iteration)

```bash
./scripts/openfdd_bacnet_poll_daemon.sh start   # max_cycles=0

# BACnet env split
docker exec openfdd-bridge printenv OPENFDD_BACNET_SERVER_ENABLED    # expect 1
docker exec openfdd-commission printenv OPENFDD_BACNET_SERVER_ENABLED # expect 0

# Core validators
./scripts/openfdd_polling_feather_validate.sh
./scripts/openfdd_drivers_validate.sh || true   # note E2BIG if tree huge

# P0 BACnet server (post-#451)
docker logs openfdd-bridge 2>&1 | grep -E 'panic|BACnet server' | tail -5
# expect: "BACnet server on UDP" and NO panic

# A′ spot checks (JWT — do not print token)
# POST :8080/api/bacnet/whois 599990-600000 → non-empty after #451
# GET  :8080/api/bacnet/driver/tree → field instances
```

Full matrix + phases: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md) (A → A′ → B → C → D).

Save artifacts:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOGDIR=workspace/logs/gh_watch_${STAMP}
mkdir -p "$LOGDIR"
curl -s http://127.0.0.1:8080/api/health | jq . > "$LOGDIR/health.json"
docker logs openfdd-bridge 2>&1 | tail -200 > "$LOGDIR/bridge.log"
```

---

## Step 5 — Post on GitHub (always #429)

### When still waiting on CI

```markdown
## Edge — watching GH Actions @ `<master_sha>`

| Workflow | Status |
|----------|--------|
| Publish Rust edge to GHCR | queued / in_progress |
| Rust Edge CI | … |

**Last bench test:** `<LAST_TESTED_SHA>` · **Waiting for:** `<PR #>` merge publish  
**Next:** deploy `:nightly` + re-run gates when GHCR green.
```

### When deploy + gates complete

```markdown
## Edge iteration N — nightly @ `<NEW_SHA>`

| Gate | Result |
|------|--------|
| GHCR publish | success |
| Deploy + health git_sha | `<NEW_SHA>` |
| BACnet server (no panic) | PASS/FAIL |
| polling_feather_validate | pass=X fail=Y |
| A′ Who-Is + tree | PASS/FAIL |

**Sign-off:** NO / YES  
**Artifacts:** `workspace/logs/gh_watch_<stamp>/`

<Product handoff block if FAIL — see main prompt>
```

```bash
gh issue comment 429 --repo bbartling/open-fdd --body-file /tmp/edge-iteration.md
# If BACnet changed:
gh issue comment 433 --repo bbartling/open-fdd --body-file /tmp/bacnet-evidence.md
```

---

## Step 6 — Loop

| Outcome | Next action |
|---------|-------------|
| **All gates PASS** | Post progress on #429; run Phase B soak if A′ green; ask maintainer for sign-off |
| **Any FAIL** | Product handoff on #429 + failing issue (#433 for BACnet); set `LAST_TESTED_SHA=$NEW_SHA`; **return to Step 1** and wait for next product PR |
| **CI failed on master** | Do not deploy; comment on #429; wait for product fix PR |
| **Same SHA as last test** | Do not claim re-test; keep watching Actions |

---

## Quick one-liner watch loop (optional background)

Poll every 15 minutes until GHCR success, then notify (does not auto-run gates — you still paste Step 3–5):

```bash
REPO=bbartling/open-fdd
while true; do
  R=$(gh run list --repo "$REPO" --workflow "Publish Rust edge to GHCR" --branch master --limit 1 \
    --json conclusion,status,headSha -q '[.status,.conclusion,.headSha[0:7]]|@tsv')
  echo "$(date -u +%H:%M:%S) GHCR: $R"
  echo "$R" | grep -q $'completed\tsuccess' && break
  sleep 900
done
echo "GHCR green — run Step 3 deploy now"
```

Automated deploy after GHCR (optional — uses site update when manifest exists):

```bash
OPENFDD_RUST_GHCR_IMAGE=ghcr.io/bbartling/openfdd-edge-rust:nightly \
OPENFDD_GHCR_POLL_SECONDS=300 \
NEW_TAG=nightly \
./scripts/openfdd_ghcr_watch_and_deploy.sh
```

---

## Current tracking (update each session)

| Item | Value |
|------|-------|
| Last tested `git_sha` | `f5f66bd` (set from bench report) |
| Pending product PR | #451 merged — wait for GHCR |
| P0 issues | [#452](https://github.com/bbartling/open-fdd/issues/452), [#453](https://github.com/bbartling/open-fdd/issues/453) |
| Primary gate | [#429](https://github.com/bbartling/open-fdd/issues/429) |
| Product agent | WSL — vibe16 prompt in repo `docs/agent/` |

---

## Rules

- **You** watch Actions and test; **WSL product** merges fixes.
- Never deploy a failed CI build.
- Never skip vibe16 `bacnet_app` preflight.
- Never close #429 yourself.
- Update `LAST_TESTED_SHA` after every full gate run.
