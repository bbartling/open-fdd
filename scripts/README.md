# `scripts/`

| Script | Purpose |
|--------|---------|
| **`start-local.ps1`** | Windows launcher: `stack/local-data`, starts gateway/MCP/UI (or `-Role` single service), sets **`OFDD_UI_PUBLIC_BASE`**, **`OFDD_MCP_OFDD_API_URL`** (same as bridge), prints the same Plots/readiness/health lines as the shell script, polls **`/health`** up to 30s. Before MCP starts (`all` or `-Role mcp`), runs **`python scripts/build_mcp_rag_index.py`** unless **`OFDD_SKIP_MCP_INDEX_BUILD=1`**. |
| **`start-local.sh`** | Same env defaults and printed hints as **`start-local.ps1`**; **`all`** runs gateway/MCP/UI in the background with logs under **`stack/local-data/logs/`**; requires **`.venv`** for `all` / `gateway` / `mcp` / `adapter`; waits on **`curl`** or **`wget`** for **`/health`**. Rebuilds **`stack/mcp-rag/index/rag_index.json`** before MCP unless **`OFDD_SKIP_MCP_INDEX_BUILD=1`**. |
| **`build_mcp_rag_index.py`** | Chunks Jekyll `docs/*.md` for MCP RAG; invoked automatically by **`start-local`** (see above) or run manually for a one-off refresh. |
| **`build_docs_pdf.py`** | Maintainer helper to combine Markdown docs and build `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |
| **`../tools/onboard_bulk_download_gui.py`** | Standalone Tkinter tool: fetch Onboard API time-series and export CSV for manual Open-FDD CSV import workflow. |

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

Both launchers strip a trailing `/` from **`OFDD_BRIDGE_URL`**, **`OFDD_UI_PUBLIC_BASE`**, and **`OFDD_MCP_REST_BASE`** in the environment they export, use the same banner copy (Plots URL uses **`printf`** / single-quoted segments so `&` and long tips are safe), and default **`OFDD_ALLOW_LOCAL_CODEX_INSTALL_CLI`** to **`0`** (set **`1`** to allow POST **`/local-codex/install-cli`**). **`OFDD_SKIP_MCP_INDEX_BUILD=1`** skips the **`build_mcp_rag_index.py`** step before MCP (faster restarts when docs did not change).

Onboard CSV bulk download GUI:

```powershell
python .\tools\onboard_bulk_download_gui.py
```
