# Bootstrap, MCP, and frontend checks

## Goals

1. Stack reaches **healthy** state for the requested mode.
2. **React** UI is reachable and core pages load without console-breaking errors (smoke level).
3. **MCP HTTP manifest** is reachable when the API is up.

## Commands (repo root `open-fdd/`)

| Intent | Command |
|--------|---------|
| Full stack | `./scripts/bootstrap.sh` |
| Collector slice | `./scripts/bootstrap.sh --mode collector` |
| Model slice | `./scripts/bootstrap.sh --mode model` |
| Engine slice | `./scripts/bootstrap.sh --mode engine` |
| Optional RAG | add `--with-mcp-rag` (manifest on port **8090**) |
| CI-style tests | `./scripts/bootstrap.sh --test` (needs `.venv` + `pip install -e ".[dev]"`) |
| Light verify | `./scripts/bootstrap.sh --verify` |

## Frontend URLs (typical)

- Vite dev / container banner: **`http://localhost:5173`**
- Via Caddy: **`http://localhost`** (see live bootstrap output)

Confirm the banner from the **current** run; ports can differ if overridden.

## MCP discovery

- Main API: `GET http://localhost:8000/mcp/manifest`
- Header when auth on: `Authorization: Bearer <OFDD_API_KEY>` from `stack/.env`
- RAG sidecar (if started): `http://localhost:8090/manifest`

Use `curl -sS -H "Authorization: Bearer …" http://localhost:8000/mcp/manifest | head` for a minimal check.

## Order of operations (token-efficient)

1. One full or mode bootstrap as requested.
2. `curl` health / manifest checks.
3. Browser smoke (few routes, one pass).
4. Only then SPARQL / heavier AI flows.

See `api_throttle.md` for pacing.
