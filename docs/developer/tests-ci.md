---
title: Tests and CI
parent: Developer Guide
nav_order: 3
---

# Tests and CI

## Local tests

```bash
./scripts/build_and_test.sh           # UI + workspace bridge pytest
python3 -m pytest open_fdd/tests -q   # PyPI package tests
cd workspace/dashboard && npm test    # dashboard unit tests (if configured)
```

## CI (GitHub Actions)

| Workflow | Trigger | Checks |
|----------|---------|--------|
| `ci.yml` | PR / push | pytest, bridge security audit, dashboard build, Jekyll docs |
| `docs-pages.yml` | push `master` | GitHub Pages site |
| `publish-open-fdd.yml` | tag `open-fdd-v*` | PyPI wheel |
| `publish-docker-addons.yml` | manual | GHCR images |

## Docs build (same as CI)

```bash
cd docs && bundle exec jekyll build -d /tmp/open-fdd-site
```

Fix any template or link errors before opening a PR that touches `docs/`.

## Security-related CI

`ci.yml` includes bridge security tests (`tests/workspace_bridge/test_security.py`). That complements — but does not replace — LAN [ZAP + Nmap scans]({% link security/zap-baseline.md %}) on each patch revision. See [Security testing cycle]({% link developer/security-testing.md %}).
