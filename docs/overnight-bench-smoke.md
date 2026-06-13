# Overnight bench smoke test

12-hour local validation on **benserver** only. Read-only.

## Command

```bash
export OPENFDD_NIAGARA_ADMIN_PASSWORD='…'
python3 scripts/run_overnight_bench_smoke.py
```

Options:

| Flag | Default | Purpose |
|------|---------|---------|
| `--duration-hours` | 12 | Total run length |
| `--checkpoint-hours` | 2 | Wake interval |
| `--dry-run` | off | Single checkpoint then exit |
| `--skip-bootstrap` | off | Skip BACnet/Niagara setup |
| `--test-poll-freq` | off | Run poll interval change test at t=0 |

## Each checkpoint

1. Cross-source validate (`bench_validate_bacnet_vs_niagara`)
2. Poll cadence report (BACnet + Niagara)
3. Targeted pytest (contract, validator, Niagara)
4. JSON + Markdown report under `reports/overnight_bench/<run_id>/`

## Final deliverable

`final_report.md` / `final_report.json` with PASS/FAIL and next actions.

## GH Actions loop

After code fixes during a wake cycle:

```bash
git add … && git commit -m "…" && git push origin fix/3.0.34-bugs
gh pr checks 300 --watch
```

No empty commits when validation-only cycles pass.
