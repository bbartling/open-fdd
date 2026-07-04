# Linux edge tester — turnkey prompt (paste into Cursor on `/home/ben/open-fdd`)

**Copy everything below the line into a new Cursor chat on the bench Linux edge host.**

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
Product fixes ship from WSL/source (vibe16 product agent). You pull :nightly and sign off on GitHub.

Acknowledged. Bench tree /home/ben/open-fdd. Channel: nightly. Primary gate #429.
Will post evidence on #429, #433, and linked issues. No git push.
```

## Your job

1. Deploy latest **GHCR `:nightly`** after each product merge
2. Run gated validation phases (A → A′ → B → C → D)
3. Post **copy-paste evidence** on GitHub issues (JSON snippets, pass/fail)
4. Update `workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md` when running local harness
5. Keep **poll daemon running** permanently (production-like)

**Never:** fix product code on bench · `docker compose down -v` · delete `workspace/` · print tokens

---

## Open GitHub issues (report on these)

| Issue | What you prove | Close when |
|-------|----------------|------------|
| **[#429](https://github.com/bbartling/open-fdd/issues/429)** | **Sign-off gate** — always comment each iteration | Bench PASS on pinned nightly + maintainer YES |
| **[#433](https://github.com/bbartling/open-fdd/issues/433)** | Drivers, BACnet Who-Is, driver tree, historian UX | A′ PASS: Who-Is JSON + field devices in tree |
| **[#431](https://github.com/bbartling/open-fdd/issues/431)** | `/api/agent/validate`, bootstrap parity | After A′ green |
| **[#430](https://github.com/bbartling/open-fdd/issues/430)** | README / MCP TLS docs | Doc review only (cookbook live on Pages) |
| **[#432](https://github.com/bbartling/open-fdd/issues/432)** | Niagara pivot | When in scope after A′ |
| **[#434](https://github.com/bbartling/open-fdd/issues/434)** | Selenium matrix | Phase C |
| **[#435](https://github.com/bbartling/open-fdd/issues/435)** | ZAP security matrix | Phase D |
| **[#437](https://github.com/bbartling/open-fdd/issues/437)** | oxigraph advisory | Note version from `/api/health` only |

**Docs for you:** [FDD Rule Cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/) · [Release channels](https://bbartling.github.io/open-fdd/operations/release-channels.html)

---

## Turn-key session start (run every visit)

```bash
cd /home/ben/open-fdd
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_COMPOSE_ROOT="$PWD"

# Auth (integrator — never echo token)
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"

# Pull + deploy nightly
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_bench_pull_ghcr.sh
NEW_TAG=nightly OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_src_sync_for_test.sh
./scripts/openfdd_rust_dcompose up -d --force-recreate
./scripts/openfdd_rust_edge_validate.sh

# Record deploy identity
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/health \
  | jq '{status,image_tag,version,git_sha}'
```

If `image_tag` is not `nightly` or health fails → stop and post on **#429**.

---

## BACnet env split (critical — verify before A′)

Compose **splits** local diagnostic server vs field Who-Is:

| Container | `OPENFDD_BACNET_SERVER_ENABLED` | Purpose |
|-----------|----------------------------------|---------|
| **openfdd-bridge** | **1** (via compose default) | Local diagnostic device **599999** |
| **openfdd-commission** | **0** (via compose default) | Field Who-Is / ReadProperty on host UDP |

Verify workspace files do **not** override compose incorrectly:

```bash
echo "=== data.env.local (bridge drivers) ==="
grep -E 'BACNET_SERVER|BACNET_MODE|BACNET_BIND' workspace/data.env.local 2>/dev/null || echo "(missing OK if compose defaults)"

echo "=== commission.env (OT commissioning) ==="
grep -E 'BACNET_SERVER|BACNET_MODE|BACNET_BIND|BACNET_IFACE' \
  workspace/bacnet/commissioning/commission.env 2>/dev/null || echo "MISSING — run bootstrap"

# commission.env must NOT force SERVER_ENABLED=1 (blocks field Who-Is)
if grep -q '^OPENFDD_BACNET_SERVER_ENABLED=1' workspace/bacnet/commissioning/commission.env 2>/dev/null; then
  echo "FAIL: set OPENFDD_BACNET_SERVER_ENABLED=0 in commission.env then recreate stack"
fi
```

After any env change:

```bash
./scripts/openfdd_rust_dcompose up -d --force-recreate
```

---

## Poll daemon (keep running forever)

```bash
./scripts/openfdd_bacnet_poll_daemon.sh stop 2>/dev/null || true
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/openfdd_bacnet_poll_daemon.sh start
./scripts/openfdd_bacnet_poll_daemon.sh status
```

Do **not** stop daemon after tests. Use bounded cycles only inside a single phase script.

---

## Phase A — Modbus poll → Feather (P0)

**Pass:** samples increment, feather files grow, historian rows increase.

```bash
OPENFDD_POLL_VALIDATE_CYCLES=5 ./scripts/openfdd_polling_feather_validate.sh

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/modbus/poll/status \
  | jq '{samples,enabled_points,last_poll,errors}'

find workspace/data/feather_store -name '*.feather' 2>/dev/null | wc -l

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/validate \
  | jq '{ok,modbus_poll,historian_row_count,feather_shards}'
```

---

## Phase A′ — BACnet Who-Is + driver tree (PRIMARY GATE)

**Pass criteria:**

- `POST /api/bacnet/whois` returns JSON within **~30 seconds** (no hang, no empty response forever)
- `GET /api/bacnet/driver/tree` returns JSON without hang
- Tree lists **field device instance(s)** from Who-Is cache — not only local diagnostic **599999**

```bash
# Who-Is (commission path — may also test via bridge API)
time curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://127.0.0.1:8080/api/bacnet/whois -d '{}' | jq .

# Driver tree
time curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/bacnet/driver/tree | jq .

# Poll status + feather from BACnet
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/poll/status | jq .
find workspace/data/feather_store/bacnet -name '*.feather' 2>/dev/null | wc -l
```

Your bench field device is an **acceptance example only** — product must work for any instance Who-Is returns. Record instances found, not hardcoded IDs in upstream.

If FAIL → post evidence on **#433** and **#429**. Do **not** patch Rust on bench. Wait for new `:nightly` (poll GH Actions at most every 15–30 min):

```bash
gh run list --workflow=rust-ghcr.yml --branch master --limit 3 \
  --json databaseId,status,conclusion,headSha,displayTitle
```

---

## Phase B — FDD soak (after A + A′ PASS)

```bash
OPENFDD_SOAK_MINUTES=10 ./scripts/openfdd_stores_fdd_soak.sh
```

Comment **#431** if `/api/agent/validate` improves.

---

## Phase C — Full rigorous + Selenium (after A′ PASS)

```bash
OPENFDD_ALWAYS_POLL=1 OPENFDD_START_BACNET_DAEMON=1 \
  ./scripts/openfdd_rigorous_full_run.sh
```

Track **#434**. Report: `workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md`

Or local closeout:

```bash
OPENFDD_BENCH_TAG=nightly OPENFDD_BENCH_POLL_CYCLES=5 \
  ./scripts/openfdd_rigorous_bench_report.sh
```

---

## Phase D — ZAP matrix (after A + B green)

```bash
OPENFDD_RUN_ZAP=1 OPENFDD_ZAP_CADDY_MATRIX=1 OPENFDD_SKIP_ZAP=0 \
  ./scripts/openfdd_soak_pcap_zap_finalize.sh
```

Track **#435**.

---

## GitHub comment template (paste every iteration on #429)

```markdown
## Edge iteration — nightly @ `<git_sha>`

**Deploy:** `image_tag` / `version` from `/api/health`
**Poll daemon:** running | stopped
**Compose:** full-edge recreated Y/N

| Phase | Result | Evidence |
|-------|--------|----------|
| A modbus→feather | PASS/FAIL | samples=… feather_files=… |
| A′ BACnet Who-Is | PASS/FAIL | whois returned in …s |
| A′ driver tree | PASS/FAIL | instances=[…] |
| B FDD soak | PASS/FAIL/SKIP | |
| C rigorous | PASS/FAIL/SKIP | |
| D ZAP | PASS/FAIL/SKIP | |

**Sign-off:** YES / NO

**Waiting on product:** #445 merged / none / <issue list>
```

Also comment on **#433** when BACnet status changes.

---

## When to close issues

You **do not** close issues yourself unless maintainer confirms. Post PASS with pinned `git_sha`; maintainer closes when re-verified.

---

## Restore local harness (if scripts missing)

Rigorous scripts are **bench-local** (Google Drive backup — not in upstream):

```bash
tar -xzf openfdd_rigorous_scripts_*.tar.gz -C /home/ben/open-fdd
chmod +x /home/ben/open-fdd/scripts/openfdd_*.sh
```

Local profile: `workspace/bench/bench_profile.toml` (never commit — OT IPs, `results_issue = 429`).

---

## Reference links

| Doc | URL |
|-----|-----|
| Product agent (WSL builds fixes) | https://github.com/bbartling/open-fdd/blob/master/docs/agent/vibe16-bacnet-feather-port-agent-prompt.md |
| Full beta cycle | https://github.com/bbartling/open-fdd/blob/master/docs/agent/bench-330-beta-cycle-agent-prompt.md |
| GHCR nightly workflow | https://github.com/bbartling/open-fdd/actions/workflows/rust-ghcr.yml |
| Vibe16 BACnet lab | https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_16 |

---

## Done when

**#429** comment says **Sign-off: YES** with Phase A + A′ + B green (C/D per open issues), poll daemon running, and all blocking issues PASS or explicitly deferred by maintainer.
