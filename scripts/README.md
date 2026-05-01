# `scripts/`

| Script | Purpose |
|--------|---------|
| **`start-local.ps1`** | Windows launcher: `stack/local-data`, starts gateway/MCP/UI (or `-Role` single service), sets **`OFDD_UI_PUBLIC_BASE`**, **`OFDD_MCP_OFDD_API_URL`** (same as bridge), prints the same Plots/readiness/health lines as the shell script, polls **`/health`** up to 30s. |
| **`start-local.sh`** | Same env defaults and printed hints as **`start-local.ps1`**; **`all`** runs gateway/MCP/UI in the background with logs under **`stack/local-data/logs/`**; requires **`.venv`** for `all` / `gateway` / `mcp` / `adapter`; waits on **`curl`** or **`wget`** for **`/health`**. |
| **`build_docs_pdf.py`** | Maintainer helper to combine Markdown docs and build `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |
| **`onboard_list_metadata.py`** | Lists Onboard buildings and sample point metadata from the API. |
| **`onboard_backfill_smoke.py`** | One-shot Onboard ingest smoke test into desktop Feather storage. |
| **`_onboard_cli.py`** | Shared helper for Onboard scripts (API key fallback from local env files). |

From the repo root:

```bash
python scripts/build_docs_pdf.py --no-pdf
```

Windows local launcher (repo-local synced data paths):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Bash local launcher:

```bash
bash ./scripts/start-local.sh
```

**`start-local.ps1` parameters:** `-Role` (`all` \| `gateway` \| `mcp` \| `ui` \| `adapter`), `-BridgeUrl`, `-SyncIntervalSeconds`.

**`start-local.sh`:** first argument is role (`all`, `gateway`, `mcp`, `adapter`, `ui`); optional env `OFDD_BRIDGE_URL`, `OFDD_TTL_SYNC_INTERVAL_SECONDS`.

Onboard metadata check:

```powershell
python .\scripts\onboard_list_metadata.py --building "Office Building"
```

Onboard ingest smoke run:

```powershell
python .\scripts\onboard_backfill_smoke.py --site-id default
```
