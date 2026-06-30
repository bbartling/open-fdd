# WSL source ↔ Linux field-install validation handoff

Updated: 2026-06-26 (post #385 merge)

## Roles

| Machine | Purpose | Do **not** |
|---------|---------|------------|
| **WSL** (`~/src/open-fdd`) | Source edits, `cargo test`, PRs, patches | Live BACnet, Docker stack, GHCR publish from laptop |
| **Linux field box** (wiped install) | Pull **GHCR** image, bootstrap, OT-LAN validation | `git clone`, `gh pr checkout`, local `docker build`, `npm run build` |

PR **#385** merged to `master` at `e3341919`. GHCR publishes on every master push to:

`ghcr.io/bbartling/openfdd-edge-rust:latest` and `:3.2.0` (from `VERSION`).

## WSL (after merge) — source-only loop

```bash
cd ~/src/open-fdd
git checkout master
git pull --ff-only

# static checks (no Docker required)
cargo fmt --all --check
cargo clippy --lib -p open_fdd_edge_prototype -- -D warnings
cargo test --workspace
cd workspace/dashboard && npm ci && npm run build
./scripts/audit_no_private_bench_hardcoding.sh
```

Patch failures reported from the Linux box → branch → PR → merge → GHCR republish → Linux `openfdd_rust_site_update.sh`.

## Linux field box — fresh GHCR install (no git checkout)

**Prerequisites:** Docker, curl, jq; OT-LAN NIC for BACnet live mode.

### 1. Bootstrap from master (pulls GHCR image)

```bash
curl -fsSL https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_rust_edge_bootstrap.sh \
  -o /tmp/openfdd_rust_edge_bootstrap.sh
bash /tmp/openfdd_rust_edge_bootstrap.sh --start --image-tag 3.2.0
```

Save integrator/operator passwords from the one-time handoff file, then delete `~/open-fdd/workspace/bootstrap_credentials.once.txt`.

Default site root: `~/open-fdd` (override with `OPENFDD_ROOT`).

### 2. Platform check (Pi / amd64)

```bash
~/open-fdd/scripts/openfdd_rust_check_ghcr_platform.sh
```

### 3. Smoke validate pulled image

```bash
~/open-fdd/scripts/openfdd_rust_edge_validate.sh
```

### 4. BACnet / Modbus / Haystack live validation

Copy profile example on the **field box** (not in git):

```bash
cp ~/open-fdd/workspace/smoke-profiles/local/local_5007_validation.local.toml.example \
   ~/open-fdd/workspace/smoke-profiles/local/local_5007_validation.local.toml
# edit: device IP, BACnet objects, Modbus host, Haystack base URL
```

Set live modes in `~/open-fdd/workspace/data.env.local` or compose env:

```bash
OPENFDD_BACNET_MODE=live
OPENFDD_MODBUS_MODE=live
# Haystack: OPENFDD_HAYSTACK_BASE + credentials — do NOT set OPENFDD_HAYSTACK_FIXTURE=1
```

Run validation orchestrator (on #385 master):

```bash
OPENFDD_VALIDATION_PROFILE=workspace/smoke-profiles/local/local_5007_validation.local.toml \
  ~/open-fdd/scripts/openfdd_one_hour_validation_report.sh
```

(`openfdd_dev_5007_report_validation.sh` lands with PR #386 — use one-hour script until then.)

NIC setup: [docs/verification/bacnet-nic-setup.md](../verification/bacnet-nic-setup.md).

### 5. After a WSL fix is merged — update site only

```bash
~/open-fdd/scripts/openfdd_rust_site_update.sh --image-tag 3.2.0
# or --image-tag latest after confirming GHCR publish
```

Backup first: `~/open-fdd/scripts/openfdd_rust_site_backup.sh`

## Protocol stacks (live paths)

| Driver | Stack |
|--------|--------|
| BACnet | [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet) via `bacnet_live.rs` |
| Modbus | [rusty-modbus](https://github.com/jscott3201/rusty-modbus) via `modbus_live.rs` |
| Haystack | [rusty-haystack-client](https://github.com/jscott3201/rusty-haystack) |
| JSON API | reqwest + JSON body parse |

Simulated CI paths remain labeled `*-simulated` / `fixture` only when explicitly configured.

## GHCR publish (GitHub Actions)

Auto on master push. Manual if needed:

```bash
gh workflow run "Publish Rust edge to GHCR" --ref master -f image_tag=3.2.0 -f tag_latest=true
gh run list --workflow="Publish Rust edge to GHCR" --limit 3
gh run watch <run-id>
```

Publish takes ~2–3 hours (multi-arch build + test gate).
