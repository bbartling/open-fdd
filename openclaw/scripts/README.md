# OpenClaw lab scripts

Small **host-side** helpers. Prefer `./scripts/bootstrap.sh` in the **repo root** for stack operations.

| Script | Purpose |
|--------|---------|
| `capture_bootstrap_log.sh` | Run bootstrap + test (or args you pass) and tee to `openclaw/logs/bootstrap-test-<ts>.txt`. |

Add more scripts here as patterns stabilize (e.g. link-check wrapper, MCP smoke `curl`).
