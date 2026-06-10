# Open-FDD agent policy

This repository is **Arrow-native FDD only** (3.0.1+). The published PyPI wheel (`open-fdd`) ships `open_fdd.arrow_runtime` (PyArrow columnar rules) and `open_fdd.playground` (Rule Lab lint/compile). **No YAML engine, no pandas in Rule Lab.** Optional graph ML (numpy/sklearn, later PyG) runs outside the sandbox — [issue #211](https://github.com/bbartling/open-fdd/issues/211).

## Default path

- Operator **Rule Lab**: extend `workspace/api/` and `workspace/dashboard/` — Python `apply_faults_arrow(table, cfg)` rules only.
- Edge **containers**: register addons in `supervisor/manifest.yaml` + `docker/images.yaml`; build with `scripts/docker_build.sh`; local stack `scripts/openfdd_stack.sh`.
- Offline rule lint: `pip install open-fdd` → `open_fdd.arrow_runtime.run_arrow_rule`.
- Do **not** add new top-level services beyond the manifest `[build]` section or `supervisor/manifest.yaml` without updating compose + Ansible templates.

## Workspace writes

- Put all generated application code under `workspace/` (see `openfdd.toml` `workspace_dir` and `scratch_dir`).
- Durable portfolio context belongs in `workspace/MEMORY.md` and `workspace/memory/` (see [skills/workspace-memory/SKILL.md](skills/workspace-memory/SKILL.md)).
- Recurring automation belongs in `workspace/cron/jobs.json` (see [skills/workspace-cron/SKILL.md](skills/workspace-cron/SKILL.md)).
- Do **not** modify `open_fdd/`, `packages/`, or `skills/` unless the operator explicitly asks for package or skill maintenance.
- Experiments stay in `workspace/scratch/` or `experiments/`; promote reviewed helpers via PR.

## FDD execution

- Author Python rules in **Rule Lab** (`apply_faults_arrow(table, cfg, context)` on PyArrow tables only); persist via `POST /api/rules/save` → **`workspace/data/rules_py/*.py`** + `rules_store.json`.
- Run batches with `POST /api/rules/batch` or `python -m openfdd_bridge.fdd_runner`; local/edge stack: `./scripts/openfdd_stack.sh up`.
- Column maps: `open_fdd.arrow_runtime.build_column_map_from_model_points` (BRICK model → historian columns).
- **Retired:** `open_fdd.engine.RuleRunner`, YAML rule files, `evaluate(row, cfg)` in new rules.

## Security

- Bind services to `127.0.0.1` by default; require explicit operator opt-in for LAN (`0.0.0.0`) or Caddy ingress.
- Secrets via environment variables or local env files — never commit credentials.
- API reference: [docs/appendix/bridge_api.md](docs/appendix/bridge_api.md). Prefer `skills/` for agent automation detail.

## Edge deploy (maintainer lab)

**Docker GHCR:** Images at `ghcr.io/bbartling/openfdd-*`. Doc: [docs/quick-start/docker.md](docs/quick-start/docker.md).

**Acme patch cycles + FDD tuning:** [skills/openfdd-edge-deploy-tune/SKILL.md](skills/openfdd-edge-deploy-tune/SKILL.md) — GHCR upgrade, `setup_gl36_fdd.py`, tuning brief/apply via Tailscale API, operational verify.

## Skill routing

| Operator intent | Start with |
|-----------------|------------|
| Python rules in Rule Lab / batch FDD | [skills/rules-crud-and-batch-run/SKILL.md](skills/rules-crud-and-batch-run/SKILL.md) |
| Column map / manifest | [skills/column-map-and-manifests/SKILL.md](skills/column-map-and-manifests/SKILL.md) |
| Graph ML (offline) | [skills/ml-lab-sklearn/SKILL.md](skills/ml-lab-sklearn/SKILL.md) · issue #211 |
| HTTP bridge API | [skills/fastapi-bridge-api/SKILL.md](skills/fastapi-bridge-api/SKILL.md) |
| React dashboard | [skills/react-operator-dashboard/SKILL.md](skills/react-operator-dashboard/SKILL.md) |
| Local feather storage | [skills/feather-local-storage/SKILL.md](skills/feather-local-storage/SKILL.md) |
| BACnet single-stack | [skills/bacnet-single-stack/SKILL.md](skills/bacnet-single-stack/SKILL.md) |
| Building check-engine | [skills/building-check-engine/SKILL.md](skills/building-check-engine/SKILL.md) |
| **Edge deploy / Acme tune** | [skills/openfdd-edge-deploy-tune/SKILL.md](skills/openfdd-edge-deploy-tune/SKILL.md) |
| BRICK TTL model | [skills/brick-ttl-data-model/SKILL.md](skills/brick-ttl-data-model/SKILL.md) |

Load each selected skill's `SKILL.md` and follow linked `references/REFERENCE.md` for route tables and env catalogs.
