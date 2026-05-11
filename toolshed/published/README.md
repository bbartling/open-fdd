# Published tools

Put **reviewed** scripts and small utilities here after they graduate from `toolshed/scratch/`.

- Prefer a **single purpose per file** and a **one-line docstring** at the top.
- **No secrets** — use env vars and bridge/MCP config instead.
- Naming: `snake_case.py` or descriptive prefixes (`probe_bridge_health.py`, `export_site_summary.py`).

This directory is **git-tracked**. Open a PR when you add or change files here.

Current helper scripts:

- `easy_aso_bench_runner.py` — preflight Open-FDD/MCP/easy-aso health and scaffold an easy-aso RPC-docked HVAC optimization agent under `toolshed/scratch/`.
