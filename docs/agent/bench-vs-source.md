# Bench vs upstream source

| Path | Purpose | Git push? |
|------|---------|-----------|
| **`/home/ben/open-fdd`** | Field bench — GHCR containers, `workspace/`, **local** test harness, reports | **No** |
| **`/home/ben/src/open-fdd`** | **Product source** — Rust edge, docs, PRs (also called `open-fdd-src`) | **Yes** (maintainers / product agent) |

## Roles

| Agent | Tree | Charter |
|-------|------|---------|
| **Bench (Linux edge)** | `/home/ben/open-fdd` | Test, document, local harness → [#429](https://github.com/bbartling/open-fdd/issues/429). **No product edits.** |
| **Product (WSL/source)** | `/home/ben/src/open-fdd` | Implement vibe16 BACnet/Feather ports, **ship PRs**. [vibe16 prompt](./vibe16-bacnet-feather-port-agent-prompt.md) |

## GHCR channels

See [Release channels](../operations/release-channels.html):

| Channel | Default for bench |
|---------|-------------------|
| `nightly` | **Yes** — pull after every master green |
| `beta` | After promotion + pinned semver |
| `latest` | Stable (not yet published) |

```bash
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_bench_pull_ghcr.sh
NEW_TAG="${OPENFDD_IMAGE_TAG:-nightly}" OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 \
  ./scripts/openfdd_rust_site_update.sh
OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-nightly}" ./scripts/openfdd_src_sync_for_test.sh
```

## Persistent polling (production-like)

| Policy | Value |
|--------|--------|
| Poll daemon | Local `openfdd_bacnet_poll_daemon.sh` — **`OPENFDD_BACNET_DAEMON_MAX_CYCLES=0`** (unlimited) |
| Bounded cycles | Only inside a single test phase (`run-for N`) |
| After tests | Daemon **stays running** — do not stop overnight |
| BACnet server 599999 | Bridge compose default **SERVER_ENABLED=1**; **commission.env `=0`** |

After env changes: `openfdd_rust_dcompose up -d --force-recreate`.

## Local profile (not in repo)

Create `workspace/bench/bench_profile.toml` on the bench only — pins OT IPs, GHCR tags, `results_issue = 429`. Never commit to upstream.
