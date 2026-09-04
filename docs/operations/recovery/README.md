# Recovery snapshots

| File | Meaning |
|------|---------|
| [lab_tuners_snapshot_pre_3.3.24.json](lab_tuners_snapshot_pre_3.3.24.json) | Open-FDD Lab tuners (~184 sum) before GL36/SV waves |
| [vibe19_ui_tuners_snapshot.json](vibe19_ui_tuners_snapshot.json) | Vibe19 Streamlit UI sliders (~414 sum) for parity planning |
| [AI_CONTEXT_HANDOFF.md](AI_CONTEXT_HANDOFF.md) | Agent/chat reboot context |

Regenerate Lab snapshot after a tuner rev:

```bash
python3 -c "..."  # or re-run inventory from sql_rules/registry.yaml
```

See parent [../BENCH_RECOVERY.md](../BENCH_RECOVERY.md).
