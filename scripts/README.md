# `scripts/`

| Script | Purpose |
|--------|---------|
| **`build_docs_pdf.py`** | Maintainer helper to combine Markdown docs and build `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |
| **`bootstrap-desktop.ps1`** | Windows bootstrap/launcher for desktop mode. Can create venv, install deps, and launch FastAPI bridge + Tauri desktop UI in separate terminals. |

From the repo root:

```bash
python scripts/build_docs_pdf.py --no-pdf
```

Windows desktop bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-desktop.ps1 -InstallDeps
```

Useful flags:

- `-NoBridge` (launch only Tauri)
- `-NoTauri` (launch only bridge)
- `-NoLaunch` (setup only, do not launch)
