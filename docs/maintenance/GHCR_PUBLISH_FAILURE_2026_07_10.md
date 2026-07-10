# GHCR Publish Failure — 2026-07-10

## Symptom

`Publish Rust edge to GHCR` (`rust-ghcr.yml`):

- **test** job: success (fmt, clippy, cargo tests, dashboard build, Docker smoke)
- **publish** job: fails in ~25s at `docker/metadata-action@v5`
- Error: `Cannot read properties of undefined (reading 'hash')`

## Confirmed runs

| Run ID | Event | SHA | Result |
| --- | --- | --- | --- |
| [29086512922](https://github.com/bbartling/open-fdd/actions/runs/29086512922) | `schedule` | `52a7d2c` | test ✓ / publish ✗ |
| [29060210628](https://github.com/bbartling/open-fdd/actions/runs/29060210628) | `workflow_dispatch` | `52a7d2c` | test ✓ / publish ✗ |

## Log excerpt (both runs)

```text
Processing tags input
  type=raw,value=nightly,enable=true,priority=200
  type=raw,value=nightly-{{date format='YYYYMMDD' timezone='UTC'}},enable=true,priority=200
  type=sha,prefix=sha-,format=short,enable=true,priority=100
Processing flavor input
  ...
##[error]Cannot read properties of undefined (reading 'hash')
```

## Root cause

`docker/metadata-action` Handlebars `date` helper signature is:

```text
{{date 'YYYYMMDD' tz='UTC'}}
```

(first positional = format; optional hash key `tz`).

The workflow used:

```text
{{date format='YYYYMMDD' timezone='UTC'}}
```

With only named parameters, Handlebars passes the options object as the first argument; the helper then reads `options.hash` where `options` is undefined → TypeError on `.hash`.

This is independent of QEMU/Buildx/login (those steps succeeded). Build-push never ran.

## Secondary observations

- Node.js 20 deprecation warnings on checkout/login/metadata/buildx/qemu actions.
- Publish job still runs GHCR prune after push; a prune failure could mark an otherwise successful publish as failed (separate risk; dedicated `ghcr-prune.yml` already exists).
- Concurrency group `rust-ghcr-nightly` with `cancel-in-progress: true` cancels overlapping push/schedule/dispatch runs (newest wins). Recent “stuck” concern (#486) shows completed cancelled/failed runs, not live hung jobs in the latest sample.
- Timeouts already present: test 60m, publish 300m.
- Docker smoke already uses isolated `$RUNNER_TEMP` workspace (PR #489).

## Fix strategy (Phase 1)

1. Remove dependency on `docker/metadata-action` for these three simple tags.
2. Compute `short_sha` and `date_tag` in a bash step; pass explicit `tags` / `labels` to `docker/build-push-action`.
3. Remove prune from the critical publish job (leave `ghcr-prune.yml`).
4. Harden smoke (trap cleanup, `reports/generated`, asset checks).
5. Bump Actions to current majors where compatible to clear Node 20 warnings.
6. Validate with actionlint + manual workflow_dispatch after merge.
