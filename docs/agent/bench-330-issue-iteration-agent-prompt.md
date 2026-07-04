# Bench agent — issue iteration (paste into Linux edge Cursor)

**Paste into Cursor on `/home/ben/open-fdd`.**

Charter: **test, document, re-verify** — **no product code fixes**, **no git push**, **no upstream PR**.

Product fixes ship from WSL/source via [vibe16-bacnet-feather-port-agent-prompt.md](./vibe16-bacnet-feather-port-agent-prompt.md).

```
Acknowledged. Bench iteration on /home/ben/open-fdd. Product agent ships PRs; I re-test after nightly publish. Primary gate #429. No git push.
```

## Where we are

| Gate | Status |
|------|--------|
| Phase 0 nightly deploy | **PASS** @ recent nightly |
| Phase A modbus → feather | **PASS** |
| A′ BACnet field Who-Is + tree | **FAIL** — awaiting vibe16 port merges (#445+) |
| Phases B–D | **SKIP** until A′ green |
| Sign-off #429 | **NO** |

Evidence stays on **#429** and **#433**.

## Product rules (global BACnet)

Open-FDD must work for **any** BACnet/IP site. Never expect upstream to hardcode private LAN IPs or a specific device instance. Your OT profile lives in **local** `workspace/bench/bench_profile.toml` only.

## Authoritative docs

- Full cycle: [bench-330-beta-cycle-agent-prompt.md](./bench-330-beta-cycle-agent-prompt.md)
- Product builder: [vibe16-bacnet-feather-port-agent-prompt.md](./vibe16-bacnet-feather-port-agent-prompt.md)

## Issue board

| Issue | Focus | Your gate |
|-------|--------|-----------|
| **#429** | Sign-off | Always comment each iteration |
| **#433** | Drivers / BACnet / Who-Is | Who-Is JSON (no hang); tree lists field instances |
| **#431** | Agent validate | After A′ green |
| **#434** | Selenium | Phase C |
| **#435** | ZAP | Phase D |

## Wait for product merge + nightly

Watch: https://github.com/bbartling/open-fdd/actions/workflows/rust-ghcr.yml  

Poll **at most every 15–30 minutes**. Need `conclusion=success` with **`headSha` newer** than your last tested nightly.

```bash
gh run list --workflow=rust-ghcr.yml --branch master --limit 3 \
  --json databaseId,status,conclusion,headSha,displayTitle
```

## Phase 1 — pull new nightly

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_bench_pull_ghcr.sh
NEW_TAG=nightly OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_src_sync_for_test.sh
./scripts/openfdd_rust_dcompose up -d --force-recreate
./scripts/openfdd_rust_edge_validate.sh
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/health | jq '{status,image_tag,git_sha}'
```

**BACnet env (must stay correct):**

| File | Required |
|------|----------|
| `workspace/data.env.local` | `OPENFDD_BACNET_SERVER_ENABLED=1` (local diagnostic server on bridge) |
| `workspace/bacnet/commissioning/commission.env` | `OPENFDD_BACNET_SERVER_ENABLED=0` (field Who-Is on commission) |

## Phase 2 — A′ BACnet (primary gate)

```bash
# Who-Is must return within ~30s (not hang)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois -d '{}' | jq .

# Tree must not hang; must show field instances from Who-Is cache
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | jq .
```

Post JSON snippets + verdict on **#429** and **#433**.

## Phase 3 — resume B–D

Only after A′ **PASS**. Follow phases in [bench-330-beta-cycle-agent-prompt.md](./bench-330-beta-cycle-agent-prompt.md).

Keep poll daemon running: `OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/openfdd_bacnet_poll_daemon.sh start`

## Never

- `docker compose down -v` · delete `workspace/` · print tokens
- Stop poll daemon after tests
- Fix product code or `git push`
- Close issues unless maintainer confirms PASS on pinned nightly
