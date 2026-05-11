# openfdd-agent-shell

Local editable operator shell for Open-FDD skills, workspace memory, cron, and Codex wakes. Not published on PyPI with the engine.

```bash
cd packages/openfdd-agent-shell
pip install -e ".[dev]"
cp ../../openfdd.toml.example ../../openfdd.toml
openfdd-agent-shell --repo-root ../..
openfdd-workspace-cron --repo-root ../.. list
openfdd-wake --repo-root ../.. --dry-run
```

Memory files live under `workspace/MEMORY.md` and `workspace/memory/`. Cron jobs live in `workspace/cron/jobs.json`.
