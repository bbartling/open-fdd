# Frontend rigorous validation (Selenium)

Headless UI regression for Open-FDD edge. On the field bench, the full Python suite lives under the operator tree; this repo ships a **curl-based smoke** gate plus optional Selenium when Chrome/Docker are available.

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

## Full bench suite (operator tree)

When copying from the field bench, place Python modules here:

- `openfdd_agent_bootstrap.py` — API commissioning regression
- `openfdd_ui_selenium.py` — headless Chrome route checks
- `openfdd_rigorous_frontend.py` — orchestrator

See `docs/verification/RIGOROUS_BENCH_SCRIPTS.md`.
