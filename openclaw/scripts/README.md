# OpenClaw lab scripts

Small **host-side** helpers. Prefer `./scripts/bootstrap.sh` in the **repo root** for stack operations.

| Script | Purpose |
|--------|---------|
| `capture_bootstrap_log.sh` | Run `./scripts/bootstrap.sh` with args you pass; tees to `openclaw/logs/bootstrap-test-<ts>.txt`; activates `.venv` if present. **Use this instead of inline `ts=` in nohup.** |
| `verify_with_log.sh` | Same as `capture_bootstrap_log.sh --verify` (one command for agents). |

Add more scripts here as patterns stabilize (e.g. link-check wrapper, MCP smoke `curl`).
