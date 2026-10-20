# Workflows (discover before assuming names)

Actual workflow files under `.github/workflows/` (open-fdd). Re-list with
`ls .github/workflows` before changing CI assumptions.

| File | Typical purpose |
| --- | --- |
| `rust-ci.yml` | Rust workspace CI (+ docs-only cookbook check) |
| `fdd-engine-ci.yml` | FDD engine / SQL pack focused CI (+ DataFusion prohibition) |
| `python-package.yml` | PyPI package tests (ECM + oracle; five suites + wheel/assets) |
| `cookbook-parity.yml` | Cookbook parity (`scripts/cookbook_parity_check.py`) |
| `docs-pages.yml` | GitHub Pages |
| `publish-open-fdd.yml` | Publish `open-fdd` to PyPI |
| `ghcr-openfdd-stack.yml` | Publish stack images; retarget `:nightly` on master |
| `rust-ghcr-mcp.yml` | Publish `openfdd-mcp` (`:nightly`) |
| `ghcr-prune.yml` | GHCR retention |
| `rust-release.yml` | Rust release |
| `security.yml` / `appsec.yml` | Security / AppSec |
| `bacnet-mqtt-container-integration.yml` | BACnet→MQTT container integration. 4.0 portal publish skips it when `openfdd-fieldbus` / `openfdd-mqtt` are absent at that sha. |
| `pypi-sql-parity.yml` | Published-package pandas oracle gate |
| `wave-c-isolated.yml` | Isolated broker / ZAP qualification umbrella. Pull requests skip when the base sha did not publish `openfdd-mqtt`. |

Removed Stage A (2026-10-15, CI/docs cleanup; no product VERSION bump):
`docs-pdf.yml` (manual echo placeholder), `historian-scale-qualification.yml`
(retired DF echo placeholder), `ecm-python.yml` (alias → `python-package.yml`).

Low-RAM hosts: **never** local `docker build` of stack images. Wait for GHCR publish, prune, pull `sha-*`, `openfdd_stack_up.sh --no-pull`.

**Railway ops (bensbench):** use **Railway CLI** for backup + hub re-pin — skill [`../skills/openfdd-railway-cli/SKILL.md`](../skills/openfdd-railway-cli/SKILL.md) · [`RAILWAY_DEPLOYMENT.md`](../../docs/operations/RAILWAY_DEPLOYMENT.md). Tip gate: `./scripts/check_ghcr_tip_stack.sh`. Do not confuse Railway CLI/MCP with `openfdd-mcp` FDD tools.

**Ops closeout:** after tip publish + re-pin, stress LAST (Wave L: mid-wave smoke + gates 11–14; full stress at L8) — [`docs/operations/STRESS_CLOSEOUT.md`](../../docs/operations/STRESS_CLOSEOUT.md). Local hub HTTP only — [`docs/operations/LOCAL_DEPLOYMENT.md`](../../docs/operations/LOCAL_DEPLOYMENT.md).

## Agent commands

```bash
gh workflow list --repo bbartling/open-fdd
gh pr checks --watch
gh run list --branch master --limit 20
gh run view <id> --log-failed
./scripts/check_ghcr_tip_stack.sh sha-<7>
railway whoami && railway service list
./scripts/railway_central_workspace_backup.sh
```
