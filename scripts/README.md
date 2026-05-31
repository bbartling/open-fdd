# `scripts/`

| Script | Purpose |
|--------|---------|
| **`run_local.sh`** | Local edge stack: **prod React build** (default), bridge, Caddy, commission agent, Ollama, MCP. `start` \| `restart` \| `stop` \| `status`. Flags: `--ui-prod`, `--ui-test`, `--ui-skip`, `--dev`. |
| **`build_and_test.sh`** | Pre-deploy gate: `build_operator_dashboard.sh test` + `pytest tests/workspace_bridge`. |
| **`build_operator_dashboard.sh`** | `prod` (default) or `test` (vitest + vite build) → `workspace/api/static/app/`. |
| **`build_docs_pdf.py`** | Maintainer helper: combined Markdown → `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |

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
