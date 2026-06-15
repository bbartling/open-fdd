---
title: ACME live validation
parent: Operations
nav_order: 24
---

# ACME live validation

**ACME** (`site_id: acme`, Acme Building) is the **live BACnet HVAC validation site** on the OT LAN. Use it for real VAV/AHU behavior, RCx rule tuning, and overnight FDD runs.

Do **not** confuse ACME with **Bench 5007** dual-source validation (site `demo`, BACnet 5007 + Niagara bench9065). Bench 5007 proves backend equivalence; ACME proves production HVAC rules on field hardware.

Reference model (no secrets): `workspace/data/fixtures/acme_data_model.json`. Validate locally:

```bash
python scripts/validate_acme_model_context.py
python scripts/validate_acme_model_context.py --json
```

## Model export / import

1. **Export** — `GET /api/model/commissioning-export` (dashboard **Import / export** tab or API).
2. **Validate** — `python scripts/validate_acme_model_context.py` on saved JSON; dashboard dry-run before import.
3. **Import** — `POST /api/model/commissioning-import` only after review. Preserve point `id`, `fdd_input`, `metadata.series_id`, and existing `fdd_rule_ids`. Never invent rule IDs.

Someday ACME will be updated from live export again; until the bench harness is stable, treat the committed fixture as the regression baseline.

## Run FDD (read-only)

| Goal | Command / API |
|------|----------------|
| Post-upgrade smoke | `./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full` |
| Selected rules | Rule Lab preview / `POST /api/playground/test-rule` |
| All enabled rules | `POST /api/rules/batch` → `workspace/data/fdd_results.json` |
| Overnight cycles | `OPENFDD_LIVE_ACME=1 python3 scripts/acme_overnight_fdd_validate.py --limit acme_vm_bbartling` |

Normal validation is **read-only**: no BACnet writes, no Pooge reset, no setpoint commands. BACnet writes require commission role + explicit enable — see [BACnet write safety]({{ "/security/bacnet-writes/" | relative_url }}).

## Reports

- Post-deploy JSON: `reports/acme-live-validate.json` (gitignored)
- Overnight FDD: under `reports/` from overnight script
- FDD batch: `workspace/data/fdd_results.json` (local edge only)

Redact tokens and hostnames before sharing.

## Fault confirmation

Rules may fire **raw** faults before **confirmed** faults. Configure `min_true_rows` and `min_elapsed_minutes` in rule `cfg` (e.g. 10 rows at 1-minute poll ≈ 10 minutes). See [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }}).

## Safe rules on ACME

Prefer read-only sensor bounds, flatline, spread (OAT vs weather), damper stuck, and zone temperature rules. Avoid supervisory writes unless explicitly commissioned and guarded.

## Related

- [ACME VAV/AHU rule guidance]({{ "/operations/acme_vav_ahu_rule_guidance/" | relative_url }})
- [Deployment validation]({{ "/ops/deployment-validation/" | relative_url }})
- [Bench 5007 long FDD smoke]({{ "/operations/bench-5007-long-fdd-smoke/" | relative_url }}) — dual-source bench only
