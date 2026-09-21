---
name: Wave U V3 MT field host
overview: "Bounded MT route matrix expansion; live host_runtime_probe + field-only evidence. Soft-OPEN sec-harness-mt-breadth + UA-08."
todos:
  - id: v3-mt-batch
    content: Convert bounded PLANNED MT routes to IMPLEMENTED with own/foreign tests
    status: pending
  - id: v3-host-field
    content: Live host_runtime_probe + field-only runtime evidence
    status: pending
  - id: v3-smoke
    content: Tip if needed → GHCR → backup/re-pin → smoke
    status: pending
isProject: false
---

# V3 — MT breadth + field/host

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)

## Soft-OPEN advanced by this cycle

- `sec-harness-mt-breadth` / UA-07 (batch, not all PLANNED routes)
- UA-08 field/host live evidence (`nessus-pass-readiness` partial)

## Work

1. Next MT batch (prefer analytics POSTs, series, buildings list): own/foreign deny + identity checks on real `tenant_ids`.
2. Run [`scripts/security/host_runtime_probe.py`](../../scripts/security/host_runtime_probe.py) on representative Linux host; retain immutable report path.
3. Field-only compose/exposure lint + runtime evidence (no cloud-exposed BACnet).
4. Tip only if product code changes; smoke after re-pin. **No MEGA.**

## Exit

- Inventory shows new IMPLEMENTED routes with tests; Soft-OPEN remains for leftover PLANNED (honest).
- Host/field evidence cited in BUG_REPORT; UA-08 PARTIAL→CLOSED only if live probe PASS.
