# `scripts/`

| Script | Purpose |
|--------|---------|
| **`run_local.sh`** | Local edge stack: **prod React build** (default), bridge, Caddy, commission agent, Ollama, MCP. `start` \| `restart` \| `stop` \| `status`. Flags: `--ui-prod`, `--ui-test`, `--ui-skip`, `--dev`. |
| **`build_and_test.sh`** | Pre-deploy gate: `build_operator_dashboard.sh test` + `pytest tests/workspace_bridge`. |
| **`build_operator_dashboard.sh`** | `prod` (default) or `test` (vitest + vite build) → `workspace/api/static/app/`. |
| **`build_docs_pdf.sh`** / **`build_docs_pdf.py`** | Combined Markdown → `pdf/open-fdd-docs.pdf` (+ `.txt`). Needs system **pandoc** + `pip install weasyprint` (or `pip install -e ".[docs]"`). CI opens a PR on `master`/`main` doc changes — merge `chore/docs-pdf-refresh`. |
| **`openfdd_edge_validate.sh`** | Bensserver / edge gate: backup → BACnet+model reset → bench setup → stack → **public check-engine (no auth)** → SPARQL/http probes → operational verify → pytest → health → log scan. `--quick` (no resets), `--full` / `--long` (full bench), `--pre-update-backup`, `--rebuild`. |
| **`docker_maintenance.sh`** | Safe prune/rebuild; never prunes bind-mounted workspace volumes. |
| **`upgrade_edge_full.sh`** | Build UI + `deploy.sh ui` + GHCR image upgrade + post-deploy check (fixes stale `static/app` on edge). |
| **`validate_fdd_backends.sh`** | Verify all enabled rules use `apply_faults_arrow` (`--docker` uses bridge container). |
| **`edge_site_backup.sh`** / **`edge_site_apply.sh`** | Site data backup/restore for remote updates (preserves model, BACnet bind, trends). |
| **`bench_feather_compact.sh`** | Local Arrow/Feather compact + column-prune timing check. |
| **`apply_bench_four_points.sh`** | Poll only OA-H/OA-T/DUCT-T/STAT ZN-T on device 5007; optional `--import-model`. |
| **`setup_bench_afdd.py`** | Bench-only BRICK + cookbook FDD rules (`demo` / `bens-office`). |
| **`setup_gl36_fdd.py`** | GL36-style FDD rules for any site (`--site-id`, `--building-id`, optional AHU bindings). |
| **`gl36_site_model.py`** | Build `workspace/data/<site>_<building>_gl36_model.json` from site pack points CSV. |
| **`gl36_mechanical_validate.py`** | Passive GL36 mechanical checks (VAV/AHU/HW) from `--host` or `--samples`. |
| **`ahu_runtime_report.py`** | Fan/system run-hour metrics (`--site-id`, `--equipment-id`). |
| **`push_ahu_setpoints.py`** | Merge BACnet setpoint rows into edge poll (`--host`, `--point-ids`). |

Site packs live under `edge_backup/local/<site_id>/<building_id>/` (see `edge_site_backup.sh`). Scripts take `--site-id` and `--building-id` instead of hardcoding customer names.

Align Ansible `edge_model_json` in host_vars with `gl36_site_model.py` output (default `workspace/data/<site>_<building>_gl36_model.json`) or pass `--out` to match an existing deploy filename.

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
