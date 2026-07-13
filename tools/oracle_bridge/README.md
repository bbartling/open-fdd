# Vibe19 → Open-FDD oracle bridge

Development-time only. **Not** a production runtime dependency.

## Boundary

```text
Vibe19 fixture/data
    → app/analytics_baseline.py
    → tests/golden/analytics/*.csv  (canonical oracle artifacts)
    → Open-FDD `fdd_cli parity`
    → DataFusion SQL results
    → .cache/parity/{parity_summary.json,parity_details.csv,parity_report.md}
```

Committed copies of the small golden CSVs live at:

`tests/fixtures/vibe19_analytics_golden/`

They are copied from Vibe19 SHA recorded in the parity report / ledger.
Do not regenerate goldens to hide drift.

## Commands

```bash
# After Open-FDD rule results exist under .cache/rule_results_*
cargo run -p fdd_cli --release -- parity \
  --oracle-dir tests/fixtures/vibe19_analytics_golden \
  --sql-results .cache/rule_results_b100_status \
  --output .cache/parity/b100 \
  --tolerance 0.5 \
  --openfdd-sha "$(git rev-parse --short HEAD)" \
  --vibe19-sha 5006a16f
```

Optional: refresh the committed golden copies from a local Vibe19 checkout:

```bash
python3 tools/oracle_bridge/sync_goldens_from_vibe19.py --vibe19-root "$VIBE19_ROOT"
```
