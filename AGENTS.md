# Agent Guide (Rust edge)

Use Rust lifecycle scripts and JSON API. No Python runtime required.

## Start session

After auth merge on `master`:

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
```

## Safe scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_check_ghcr_platform.sh
./scripts/openfdd_rust_edge_validate.sh
```

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print secrets or tokens
- expose API on public internet
- write BACnet without explicit human approval

## Assignment rule

Bind drivers → Haystack IDs → FDD/CDL via `/api/model/assignments`.

See [docs/ai-agent-context.md](docs/ai-agent-context.md).
