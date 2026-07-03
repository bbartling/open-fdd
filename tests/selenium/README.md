# Frontend rigorous validation (Selenium)

Headless UI regression for Open-FDD edge. This repo ships a **curl-based smoke** gate; the full Python Selenium suite lives on the **field bench only** (not in upstream).

## Quick smoke (CI-friendly)

```bash
./scripts/openfdd_ui_smoke.sh
```

Requires a running edge at `http://127.0.0.1:8080` with integrator auth in `workspace/auth.env.local`.

## Rigorous wrapper

```bash
./tests/selenium/openfdd_frontend_rigorous.sh
```

Runs UI smoke and records artifacts under `workspace/logs/frontend_rigorous_<UTC>/`.

## Full bench suite (operator tree only)

On `/home/ben/open-fdd`, restore Python modules from your local backup tarball:

- `openfdd_agent_bootstrap.py` — API commissioning regression
- `openfdd_ui_selenium.py` — headless Chrome route checks
- `openfdd_rigorous_frontend.py` — orchestrator

These are **not** published in `bbartling/open-fdd`.
