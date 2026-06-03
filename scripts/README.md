# `scripts/`

| Script | Purpose |
|--------|---------|
| **`run_local.sh`** | Local edge stack: **prod React build** (default), bridge, Caddy, commission agent, Ollama, MCP. `start` \| `restart` \| `stop` \| `status`. Flags: `--ui-prod`, `--ui-test`, `--ui-skip`, `--dev`. |
| **`build_and_test.sh`** | Pre-deploy gate: `build_operator_dashboard.sh test` + `pytest tests/workspace_bridge`. |
| **`build_operator_dashboard.sh`** | `prod` (default) or `test` (vitest + vite build) → `workspace/api/static/app/`. |
| **`build_docs_pdf.py`** | Maintainer helper: combined Markdown → `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |
| **`openfdd_edge_validate.sh`** | Bensserver / edge gate: backup → BACnet+model reset → bench setup → stack → SPARQL/http probes → operational verify → pytest → health → log scan. `--full`, `--quick`, `--pre-update-backup`, `--rebuild`. |
| **`docker_maintenance.sh`** | Safe prune/rebuild; never prunes bind-mounted workspace volumes. |
| **`edge_site_backup.sh`** / **`edge_site_apply.sh`** | Site data backup/restore for remote updates (preserves model, BACnet bind, trends). |

## Typical workflow

```bash
./scripts/build_and_test.sh
./scripts/run_local.sh restart
# Open http://127.0.0.1/ (Caddy) or http://127.0.0.1:8765/ (Caddy off)
```

Skip UI rebuild when unchanged:

```bash
./scripts/run_local.sh restart --ui-skip
```
