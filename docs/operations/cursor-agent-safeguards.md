---
title: Cursor agent safeguards
parent: Operations
nav_order: 13
---

# Cursor agent safeguards

Long-running shell jobs **crash Cursor** when agents block-wait, poll in loops, or stay attached to child processes.

## What crashes the IDE

| Unsafe (agents) | Why |
|-----------------|-----|
| `pytest tests/workspace_bridge` (~4 min) | Blocks chat turn; heavy output |
| `./scripts/smoke_paired_fdd_harness.sh --short` attached | 30 min blocking wait |
| `sleep 60` / `Await` / `tail -f` poll loops | Agent keeps terminal session alive |
| Running harness `.py` directly from agent | Same as attached smoke |

## Safe pattern

Launch in **systemd user unit** (or `setsid`), then **poll status once** — never wait.

### Paired FDD smoke

```bash
./scripts/run_paired_fdd_smoke_isolated.sh --short --bench-only
./scripts/smoke_paired_fdd_status.sh --mode short
```

### Bench 5007 half-hour smoke (FDD + health + RCx)

```bash
./scripts/smoke_bench_5007_half_hour.sh
./scripts/smoke_bench_5007_half_hour_status.sh
```

### workspace_bridge pytest (CI parity)

```bash
./scripts/run_workspace_bridge_pytest_isolated.sh
./scripts/workspace_bridge_pytest_status.sh
```

### Humans in tmux/SSH

```bash
./scripts/smoke_paired_fdd_harness.sh --short --attached
```

`--attached` is **refused** when `CURSOR_AGENT` is set.

## Implementation

| File | Role |
|------|------|
| `scripts/lib/cursor_agent_guard.sh` | Shared refuse/poll helpers |
| `scripts/run_paired_fdd_smoke_isolated.sh` | systemd smoke launcher |
| `scripts/smoke_paired_fdd_status.sh` | Read-only smoke status |
| `scripts/run_workspace_bridge_pytest_isolated.sh` | systemd pytest launcher |
| `scripts/workspace_bridge_pytest_status.sh` | Read-only pytest exit code |

Default: `smoke_paired_fdd_harness.sh` redirects to the isolated launcher unless `--attached`.
