# Migration matrix (current)

| Area | Disposition | Notes |
| --- | --- | --- |
| Product UI | React SPA (`frontend/web`) | Sole product surface |
| Product FDD | DataFusion SQL (`sql_rules/`) | No pandas in request path |
| Product analytics | `/api/analytics/*` historian DF | Client Plotly presentation |
| PyPI `open_fdd` | Keep forever | Third-party / oracle / ECM / reporting libs |
| SQL + pandas cookbooks | Keep both | Production vs oracle expressions |
| vibe19 playground | External companion | Pandas demo image |
| vibe20 playground | External companion | EnergyPlus studio |
| WattLab AFDD zip export | Offline tooling | `tools/wattlab_export`; opt-in env only |
| `edge/`, `os/` | Keep | Future concepts |
