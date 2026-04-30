# `scripts/`

| Script | Purpose |
|--------|---------|
| **`start-local.ps1`** | Windows launcher that sets repo-local desktop data defaults (`stack/local-data`) and starts gateway/MCP/UI (or individual roles). |
| **`start-local.sh`** | Bash launcher with the same repo-local defaults; can run all services in background with logs under `stack/local-data/logs`. |
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
