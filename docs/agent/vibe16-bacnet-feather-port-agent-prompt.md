# Product agent — Vibe16 BACnet + Feather port (paste into WSL / source Cursor)

**Paste into Cursor on the Open-FDD source tree** (`/home/ben/src/open-fdd` — also referenced as `open-fdd-src`).

Charter: **implement** validated vibe16 lab patterns in product Rust; **ship PRs**; bench re-verifies on [#429](https://github.com/bbartling/open-fdd/issues/429) after merge.

```
Acknowledged. Product agent on /home/ben/src/open-fdd. Implement vibe16 BACnet/Feather patterns, open PRs, no bench-only hacks. Bench signs off on #429 after nightly publish.
```

---

## Charter flip (read first)

| Old bench agent | **New product agent (you)** |
|-----------------|----------------------------|
| Test only, no product fixes | **Implement** vibe16 patterns in `open-fdd` |
| Wait for nightly sha | **Ship PRs** → CI → GHCR `:nightly` → bench re-tests |
| File builder prompts for WSL | **You are the builder** on WSL/source |
| Patch bench tree | **Never** — bench `/home/ben/open-fdd` is deploy + sign-off only |

| Old WSL role | **New bench agent (Linux edge)** |
|--------------|----------------------------------|
| — | Pull `:nightly`, run local harness, post on **#429** |
| — | **No** Rust/TS edits, **no** git push from bench |
| — | Prompt: [bench-330-beta-cycle-agent-prompt.md](./bench-330-beta-cycle-agent-prompt.md) |

---

## Reference lab (validated working)

| Item | Link |
|------|------|
| **Vibe16 index** | https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_16 |
| **Open-FDD BACnet mimic** (599999) | [openfdd-bacnet-mimic](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_16/openfdd-bacnet-mimic) |
| **BACnet → Feather concept** | [openfdd-bacnet-feather-concept](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_16/openfdd-bacnet-feather-concept) |
| **rusty-bacnet upstream** | https://github.com/jscott3201/rusty-bacnet |

Lab proves:

1. **Who-Is / I-Am** — mimic answers discovery; field devices learnable on LAN
2. **ReadProperty** — unicast reads return PV without hang
3. **Poll → Feather** — single-process writer + atomic shard files; tail binary for debug
4. **Commission vs bridge env split** — server enabled only where intended

Port **behavior**, not file-for-file copy. Open-FDD uses **wide** pivot rows + per-source Feather shards (`edge/src/historian/feather_store.rs`).

---

## Product map — vibe16 → Open-FDD

| Vibe16 concept | Open-FDD target | Status / issue |
|----------------|-----------------|----------------|
| Mini-device + poller + Feather writer | `feather_store::write_wide_shard` + modbus/bacnet poll | Phase A **PASS** on bench (modbus) |
| Who-Is cache → tree shells | `whois_discovered.json`, `ensure_field_devices_from_whois`, GET tree **no live I/O** | **#433** / PR #445 |
| Who-Is API timeout (no hang) | `whois_json` + `bacnet_live::whois_devices_with_range` | PR #445 |
| Compose env split (bridge ≠ commission) | `docker-compose.yml` + `commission.env` defaults | PR #445 |
| BACnet mimic 599999 object model | `bacnet_server_runtime.rs` / commission stack | Validate on bench |
| Field device poll → historian | `persist_bacnet_reads_to_historian` | Bench A′ blocked until Who-Is green |
| `feather_tail` debug | `GET /api/historian/feather-store` or agent validate | **#431** |

**Global rule:** no private bench IPs or fixed device instances in product code. Tests use TEST-NET / generic `equip:your-ahu`.

---

## Patch cycle (turn-key — you run this loop)

### Cycle 0 — sync

```bash
cd /home/ben/src/open-fdd
git fetch origin master && git checkout master && git pull
gh issue list --state open --limit 20
gh pr list --state open
```

Read open PRs on `master`. **#445 merged** — first edge iteration should test BACnet compose split + Who-Is shell.

### Cycle 1 — pick one vertical slice

Choose **one** row from the product map. Example order:

1. **BACnet Who-Is + tree shells** (unblocks bench A′) — #433, #445
2. **BACnet poll → feather + pivot** (field device reads persist)
3. **Agent validate parity** — #431 (`/api/agent/validate` documents poll + feather counts)
4. **Driver UX** — #433 UI polish (after APIs stable)

### Cycle 2 — implement + test locally

```bash
cd /home/ben/src/open-fdd/edge
cargo fmt --all
cargo clippy --all-targets -- -D warnings
cargo test
cd ../dashboard && npm test -- --run
```

Docker smoke (when touching drivers/compose):

```bash
./scripts/openfdd_rust_edge_validate.sh
```

### Cycle 3 — PR

```bash
git checkout -b fix/vibe16-<slice>
git add -A && git commit -m "fix(bacnet): <what> (vibe16 port, #433)"
git push -u origin HEAD
gh pr create --title "fix(bacnet): <title> (vibe16 port)" \
  --body "## Summary
- Ports vibe16 lab pattern: <link>
- Closes / unblocks: #433 / #429

## Bench validation (edge agent)
- [ ] Pull nightly after merge
- [ ] POST /api/bacnet/whois returns JSON in <30s (no hang)
- [ ] GET /api/bacnet/driver/tree lists field instances from Who-Is cache
- [ ] Historian feather count grows after BACnet poll cycle

## Test plan
- cargo test
- compose smoke"
```

### Cycle 4 — after merge

Comment on **#429** and **#433**:

```markdown
**Product:** merged PR #NNN @ `<sha>` — GHCR `:nightly` publishing.
**Bench:** please re-run orchestration loop (linux-edge-tester-prompt) — all-drivers matrix + A→A′→B.
```

Do **not** poll GH Actions in a tight loop. Check `rust-ghcr.yml` once per 15–30 min.

### When bench posts Product handoff (FAIL block)

1. Read JSON evidence on **#429** / **#433** — identify failing driver (Modbus, BACnet, Haystack, historian)
2. Reproduce locally if possible (`cargo test`, compose smoke)
3. Ship **one** focused PR; comment on the issue with PR link
4. After merge, post nightly sha on issue — bench owns re-test

**Do not** ask bench to patch Rust. **Do not** close issues — bench re-verifies first.

---

## Implementation notes (from vibe16 lab)

### Who-Is / driver tree

Lab: Who-Is returns I-Am; tree is built from discovered instances, not hardcoded.

Product files:

- `edge/src/drivers/bacnet.rs` — `whois_json`, `cached_whois_instances`, `ensure_field_devices_from_whois`
- `edge/src/drivers/bacnet_live.rs` — `whois_devices_with_range`
- `workspace/bacnet/commissioning/commission.env` — **`OPENFDD_BACNET_SERVER_ENABLED=0`** default on commission service

**Acceptance (bench validates — do not hardcode bench device ID in product):**

- `POST /api/bacnet/whois` → `{ "ok": true, "devices": [...] }` within timeout
- `GET /api/bacnet/driver/tree` → includes **field** instances from cache (not only local diagnostic server)
- GET must **not** block on live Who-Is (use cache / shells)

### Feather store

Lab: `openfdd-bacnet-feather-concept` writes atomic `shard-<epoch>-<uuid>.feather`.

Product: `edge/src/historian/feather_store.rs` — `write_wide_shard(source, site_id, ts, columns)`.

Ensure BACnet poll path calls `write_wide_shard("bacnet", ...)` **and** pivot append (dual-write). Modbus path is reference.

### Env / compose split

Bridge container must not inherit commission `OPENFDD_BACNET_SERVER_ENABLED=1`. Document in `docs/drivers/bacnet.md` after fix.

---

## Leave for bench validation (do not self-sign-off)

These require the **Linux edge** agent on `/home/ben/open-fdd`:

| Gate | Bench check |
|------|-------------|
| Phase 0 | Nightly deploy, health `image_tag` |
| Phase A | Modbus poll → feather files + historian growth |
| Phase A′ | BACnet Who-Is + driver tree field devices |
| Phase B | Driver tab refresh / UI |
| Phase C | Selenium harness (**#434**) |
| Phase D | ZAP matrix (**#435**) |
| Sign-off | **#429** — integrator-ready verdict |

Product agent posts **merge + sha**; bench posts **pass/fail evidence**.

---

## Related docs (shipped)

| Doc | URL |
|-----|-----|
| **FDD Rule Cookbook** | https://bbartling.github.io/open-fdd/rules/cookbook/ |
| Release channels | https://bbartling.github.io/open-fdd/operations/release-channels.html |
| BACnet driver | https://bbartling.github.io/open-fdd/drivers/bacnet.html |
| Bench cycle prompt | [bench-330-beta-cycle-agent-prompt.md](./bench-330-beta-cycle-agent-prompt.md) |

---

## Never

- Hardcode bench BACnet IPs or device **5007** in product/docs meant for global use
- Delete `workspace/` on bench
- `docker compose down -v` / volume prune
- Print secrets or JWT tokens
- Push from bench tree
- Embed LLM API keys in edge stack

---

## Current open issues (product agent owns fixes)

| Issue | Focus |
|-------|--------|
| **#429** | Bench sign-off tracker — comment after each merge |
| **#433** | Drivers / BACnet / historian UX — **primary** |
| **#431** | Agent validate / bootstrap parity |
| **#430** | README + MCP TLS docs |
| **#432** | Niagara pivot pipeline |
| **#434** | Selenium test matrix |
| **#435** | ZAP security re-run |
| **#437** | oxigraph / quick-xml advisory |

Close issues only when bench evidence + CI prove fix. Defer **#369** (WASM connectors) — not in vibe16 scope.
