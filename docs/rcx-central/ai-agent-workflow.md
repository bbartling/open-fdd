# AI agent workflow vs runtime use

## Runtime analyst (no git clone)

1. `docker compose -f docker/rcx-central/docker-compose.yml up`
2. Open http://localhost:8050
3. Add ACME Edge via Tailscale URL in Edge Connections
4. Test → Save → Mechanical Summary → RCx Report Builder → DOCX

Kill container when done. Data persists in Docker volumes.

## Developer / coding agent (git working tree)

Use Cursor or Codex against the `open-fdd` repo to change Central code, tests, and docs. This requires a clone or working tree — **not** the runtime Docker image alone.

## Secrets

- Never commit `portfolio/config/credentials.json` or `sites.json` with passwords
- Use env vars for CI: `OFDD_AGENT_PASSWORD`, etc.
- Live ACME tests: `OPENFDD_LIVE_ACME=1` only

## Model routing (test triage)

See `AGENTS.md` — classify CI failures as SIMPLE (primary model) vs COMPLEX (thinking model) before processing.
