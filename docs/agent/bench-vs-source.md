# Bench vs upstream source

| Path | Purpose | Git push? |
|------|---------|-----------|
| **`/home/ben/open-fdd`** | Field bench — GHCR containers, `workspace/`, test harness, reports | **No** |
| **`/home/ben/open-fdd-src`** | Read-only source — bug analysis, FIX prompts for WSL | **No** |

## Tester role

- **Test, document, maintain scripts** on the bench tree
- Results → `workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md` + GitHub [#429](https://github.com/bbartling/open-fdd/issues/429)
- **Do not fix product code** on bench — write WSL builder prompts with paths from `open-fdd-src`

## GHCR channels

See [Release channels](../operations/release-channels.html):

| Channel | Default for bench |
|---------|-------------------|
| `nightly` | **Yes** — pull after every master green |
| `beta` | After promotion + pinned semver |
| `latest` | Stable (not yet published) |

```bash
./scripts/openfdd_bench_pull_latest.sh   # tries nightly → beta → semver
NEW_TAG="${OPENFDD_IMAGE_TAG:-nightly}" OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 \
  ./scripts/openfdd_rust_site_update.sh
OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-nightly}" ./scripts/openfdd_src_sync_for_test.sh
```

## Persistent polling (production-like)

| Policy | Value |
|--------|--------|
| Poll daemon | `./scripts/openfdd_bacnet_poll_daemon.sh start` with **`OPENFDD_BACNET_DAEMON_MAX_CYCLES=0`** (unlimited) |
| Bounded cycles | Only inside a single test phase (`run-for N`) |
| After tests | Daemon **stays running** — do not stop overnight |
| BACnet server 599999 | `OPENFDD_BACNET_SERVER_ENABLED=1` in `data.env.local` + `commission.env` |

After env changes: `openfdd_rust_dcompose up -d --force-recreate`.

## Profile

Copy `workspace/bench/bench_profile.toml.example` → `workspace/bench/bench_profile.toml` and set `results_issue = 429`.
