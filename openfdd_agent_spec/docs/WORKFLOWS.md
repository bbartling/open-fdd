# Workflows (discover before assuming names)

Actual workflow files under `.github/workflows/` (open-fdd). Re-list with
`ls .github/workflows` before changing CI assumptions.

| File | Typical purpose |
| --- | --- |
| `rust-ci.yml` | Rust workspace CI (+ docs-only cookbook check) |
| `fdd-engine-ci.yml` | FDD engine / DataFusion focused CI |
| `python-package.yml` | Python package tests |
| `ecm-python.yml` | ECM Python package tests |
| `cookbook-parity.yml` | Cookbook parity (`scripts/cookbook_parity_check.py`) |
| `docs-pages.yml` | GitHub Pages |
| `docs-pdf.yml` | Docs PDF |
| `publish-open-fdd.yml` | Publish `open-fdd` to PyPI |
| `ghcr-openfdd-stack.yml` | Publish stack images; retarget `:nightly` on master |
| `rust-ghcr-mcp.yml` | Publish `openfdd-mcp` (`:nightly`) |
| `ghcr-prune.yml` | GHCR retention |
| `rust-release.yml` | Rust release |
| `security.yml` / `appsec.yml` | Security / AppSec |

Low-RAM hosts: **never** local `docker build` of stack images. Wait for GHCR publish, prune, pull `sha-*`, `openfdd_stack_up.sh --no-pull`.

**Ops closeout:** after tip publish + re-pin, stress LAST — [`docs/operations/STRESS_CLOSEOUT.md`](../../docs/operations/STRESS_CLOSEOUT.md). Local hub HTTP only — [`docs/operations/LOCAL_DEPLOYMENT.md`](../../docs/operations/LOCAL_DEPLOYMENT.md).

## Playground (reference)

| Workflow | Role |
| --- | --- |
| `vibe19-ghcr.yml` | vibe19 image |
| `vibe20-ghcr.yml` | vibe20 image |

## Agent commands

```bash
gh workflow list --repo bbartling/open-fdd
gh pr checks --watch
gh run list --branch master --limit 20
gh run view <id> --log-failed
```
