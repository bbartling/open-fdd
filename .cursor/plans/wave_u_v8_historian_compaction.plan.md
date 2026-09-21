---
name: Wave U V8 historian compaction
overview: "H4 offline ops surface + runtime read/compaction coordinator. Soft-OPEN historian-n-building-scale. After V7."
todos:
  - id: v8-h4-ops
    content: Verify/document H4 offline CLI/API validate-before-publish
    status: pending
  - id: v8-runtime-coordinator
    content: Coordinator serializes compaction vs DataFusion scans
    status: pending
  - id: v8-evidence
    content: Synthetic small-file fixture compact + concurrent negative; Soft-OPEN close or PARTIAL honesty
    status: pending
isProject: false
---

# V8 — `historian-n-building-scale` compaction

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)  
**Architecture:** [`openfdd_agent_spec/docs/HISTORIAN_ARCHITECTURE.md`](../../openfdd_agent_spec/docs/HISTORIAN_ARCHITECTURE.md)

## Soft-OPEN closed by this cycle

- `historian-n-building-scale` (offline H4 + runtime coordinator; else PARTIAL honesty)

## Work

1. Ship/verify **operator H4 offline** surface: partition-bounded memory, validate-before-publish, tombstone retire, rollback honesty.
2. Implement **runtime coordinator** serializing compaction vs DataFusion scans (no publish-first dup / retire-first gap without locks).
3. Admin capacity small-file strip: wire trigger/status; Railway maintenance window for live compact.
4. Evidence: multi-building small-file fixture → compact → stable row counts; concurrent scan+compact fails closed or waits.
5. Tip → GHCR → smoke. Targeted retest only; **no full MEGA** unless query contracts change.

## Exit

- Soft-OPEN CLOSED when offline H4 documented **and** runtime coordinator has CI + disposable soak; otherwise PARTIAL with named residual.
