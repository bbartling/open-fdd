# Open-FDD UI (`services/ui`) — Streamlit engineering app

**One Streamlit process** unites vibe19 FDD / RCx / Jobs workflows with vibe20 **WattLab dump** export. There is no second Streamlit app for WattLab/EnergyPlus inside Open-FDD (EnergyPlus stays in the external vibe20 playground).

| Concern | Source of truth |
|---------|-----------------|
| Production FDD math | Central DataFusion SQL — `sql_rules/registry.yaml` (**63**) via `POST /api/fdd/run` |
| Pandas cookbook | `app/rules/cookbook_catalog.py` (**59**) — **kept** for docs, plots/analytics, and oracle; emergency FDD only with `OPENFDD_ALLOW_PANDAS_FDD=1` |
| Online cookbooks | [DataFusion SQL](https://bbartling.github.io/open-fdd/rules/cookbook/datafusion-sql-cookbook.html) · [Pandas](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html) |
| Jobs | Sidebar **Jobs (persistent)** → `workspace/jobs/` (`app/job_store.py`) |

**This is the product UI image** `ghcr.io/bbartling/openfdd-ui` (not a detached educational demo).

**Quick links:** package layout [`docs/PACKAGE_SPEC.md`](docs/PACKAGE_SPEC.md) · agent brief root [`AGENTS.md`](../../AGENTS.md) · architecture [DataFusion-first](../../docs/architecture/datafusion-first.md) · [Job workspaces](../../docs/architecture/job-workspaces.md)

## Highlights

- **Run Rules** → central SQL (JWT-aware `central_client`)
- Full **59** pandas cookbook retained for analytics / oracle / emergency gate
- Zip package ingest (`openfdd_package_v1`), role mapping, RCx plots, metering
- **WattLab dump v3** on Export — handoff zip for external vibe20 (not an in-repo EnergyPlus runner)
- Persistent **Jobs** under `workspace/jobs/`

## Quick start (dev)

```bash
cd services/ui
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Against a stack, point at central (`OPENFDD_CENTRAL_URL`) with JWT env as needed.

## Docker / GHCR

Use the stack recipes (`docker/compose.standalone.yml`) with `OPENFDD_IMAGE_TAG=sha-*` or `:nightly`. See [`docker/VERSION_MANIFEST.md`](../../docker/VERSION_MANIFEST.md).
