# Streamlit Community Cloud notes

## Deploy

1. Push `vibe_code_apps_19` (or set Cloud **app path** to this folder in the monorepo).
2. Streamlit Cloud → New app:
   - **Main file:** `streamlit_app.py`
   - **Python:** 3.11+
   - Dependencies: `requirements.txt` in this folder (Cloud installs that file)
3. Optional secrets / env:
   ```text
   APP_MODE=cloud
   ```
4. Users pick **Data source → Zip package** and upload `openfdd_package_v1` — see [PACKAGE_SPEC.md](PACKAGE_SPEC.md).

**No Dockerfile on Community Cloud.** The repo `Dockerfile` is for self-host / local parity only — see [DOCKER.md](DOCKER.md).

## Unified app (local + cloud)

One sidebar picker:

- **Folder** — local historian tree (hidden when `allow_server_paths` is false)
- **Zip package** — always available; uncached; **Clear session** wipe
- **Session restore (Cloud-safe)** — download / upload `session_config.json` (+ optional `fault_settings.json`)
- **AI agent / package help** expander — agent steps + limits

Disk saves (`configs/`) become **downloads** on shared/Cloud hosts. Zip extract stays in OS temp (`vibe19_*`).

## Session round-trip (Cloud-friendly)

Tuned mapping / thresholds are **not** persisted on the Cloud host. Use browser download/upload:

1. Upload building zip (`openfdd_package_v1`).
2. Map roles / tune rule params (sidebar + Mapping / Overview).
3. **Download session config** → `session_config.json` (`openfdd_session_v1`: `unit_system`, `prefer_web_oat`, `role_map`, `params`, plant toggles). Optionally download **fault settings** (`params` only).
4. Later session: upload the **same zip**, then **Upload session config** → Apply — restores into `st.session_state` (no server path).
5. Re-run rules.

Same controls live in the sidebar and on the **Export** tab. Local agents can still paste JSON paths when `APP_MODE=local`.

## Honest limits

- One shared Python process for all visitors
- Session wipe is **best-effort**
- Not a security boundary for sensitive building data
- Keep zips within **two-tier** defaults:
  - Browser: `.streamlit/config.toml` → `server.maxUploadSize = 500` (stock Streamlit says “200MB per file” without this)
  - Agent/CLI/path: package_io **2048 MB** (`DEFAULT_PACKAGE_MB`) — prefer path load / `agent_afdd` for large buildings
  - See [PACKAGE_SPEC.md](PACKAGE_SPEC.md) / [DOCKER.md](DOCKER.md)
- Sidebar / Overview show loaded size vs package limit.

## AI agents

Open the public URL → upload zip → tune → download `session_config.json` for the next visit. No locked per-agent backend on Streamlit Cloud. Headless: `scripts/agent_afdd.py` + optional `session_config` / `fault_settings` in the export bundle.

Self-host image: [DOCKER.md](DOCKER.md) / `ghcr.io/<owner>/vibe19` (GHCR stores the image; it does not host the app).
