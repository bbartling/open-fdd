# Cursor prompt — vibe19 / py-bacnet-stacks playground

**Target repo:** `bbartling/py-bacnet-stacks-playground` (vibe19 image / agent_afdd)  
**Do NOT patch on bensbench / open-fdd.** OpenFDD tip is healthy; this is export-path polish only.

## Context (2026-08-13)

Synthetic-59 target-pair soak on bensbench:

| Side | Score | Notes |
|------|-------|-------|
| OpenFDD SQL (`sha-182dbc3`) | **59/59** | Product truth |
| vibe19 `:latest` | **59/59** | Rules OK; export crash after summary |

Command:

```bash
docker exec vibe19 python scripts/agent_afdd.py \
  --package /data/OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip \
  --out /data/synthetic_59_agent_out \
  --params /data/synthetic_59_params.json \
  --run-rules --no-bootstrap --export-profile summary
```

Exit **rc=1** after printing rule tallies. `fdd_summary.csv` is written; soak continues. Crash:

```text
TypeError: numpy boolean subtract, the `-` operator, is not supported
  ... pandas ... quantile ... _lerp ... diff_b_a = b - a
```

Root: export/summary path runs `quantile` on a **boolean** Series (likely a fault/flag column). Fix by coercing to float/int before quantile, or skip bool columns in the export profile.

## Also check (Building 100 mech OAT bins)

OpenFDD was fixed in [#715](https://github.com/bbartling/open-fdd/pull/715) (status-before-amps; prefer web OAT). If vibe19 Overview bins still disagree after OFDD re-ingest with `dry_bulb_f → web_oa_t`, compare against pandas `open_fdd.analytics.core.mech_cooling_oat_bins` / `_select_mech_cooling_proof` hierarchy. Product truth is OpenFDD DataFusion after #715.

See open-fdd `docs/agent/B100_MECH_OAT_BINS_FIX.md`.

## Done when

1. `agent_afdd.py --export-profile summary` exits 0 on the synthetic-59 zip.
2. No bool-quantile TypeError in export.
3. Optional: rebuild/push `ghcr.io/bbartling/vibe19:latest` (or `:develop`) for bensbench pull.

## Out of scope

- Editing `expected_faults.csv` / OpenFDD goldens
- Local Docker image builds on bensbench (low RAM)
- Changing OpenFDD SQL rules for this export bug
