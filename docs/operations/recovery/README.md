# Recovery snapshots

| File | Meaning |
|------|---------|
| [lab_tuners_snapshot_pre_3.3.24.json](lab_tuners_snapshot_pre_3.3.24.json) | Open-FDD Lab tuners (~184 sum) before GL36/SV waves |
| [vibe19_ui_tuners_snapshot.json](vibe19_ui_tuners_snapshot.json) | Vibe19 Streamlit UI sliders (~414 sum) for parity planning |
| [lab_vibe19_tuner_gap_matrix_g0.json](lab_vibe19_tuner_gap_matrix_g0.json) | Wave G G0: tip Lab **217** vs Vibe19 **414** (gap 197 = ~76 SQL-bindable + ~156 gate trio) |
| [lab_tuners_snapshot_post_wave_g.json](lab_tuners_snapshot_post_wave_g.json) | Lab tuners after Wave G Vibe19 parity (~444 sum) |
| [lab_tuners_snapshot_post_wave_g.json](lab_tuners_snapshot_post_wave_g.json) | Lab tuners after Wave G Vibe19 parity (~444 sum) |
| [AI_CONTEXT_HANDOFF.md](AI_CONTEXT_HANDOFF.md) | Agent/chat reboot context |

**RCx plots by HVAC type:** [`../../RCX_PLOTS_BY_HVAC.md`](../../RCX_PLOTS_BY_HVAC.md)

Regenerate Lab snapshot after a tuner rev:

```bash
python3 -c "..."  # or re-run inventory from sql_rules/registry.yaml
```

See parent [../BENCH_RECOVERY.md](../BENCH_RECOVERY.md).
