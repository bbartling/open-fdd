# Browser ↔ Central contract conventions (P1-M2-01)

**Contract version:** `openfdd.api.contract.v1`  
**Compatibility:** additive fields within a version; breaking changes bump the version string exposed on `GET /api/capabilities` → `contract.contract_version`.

## Request identity

- Client **should** send `x-request-id` (UUID).
- Central middleware ensures every response echoes `x-request-id` (generated if missing).

## Error envelope

```json
{
  "error": {
    "code": "mapping.role_missing",
    "message": "Human-readable summary",
    "details": {},
    "retryable": false,
    "request_id": "..."
  }
}
```

Helpers live in `services/central/src/contract.rs` (`ApiErrorEnvelope`, `json_error`).

## Timestamps & numbers

- Timestamps: RFC 3339 with explicit offset (prefer `Z` or numeric offset).
- Missing floats: JSON `null` (never NaN/Inf in wire JSON).

## Concurrency & idempotency

- Jobs: `expected_meta_revision` on mutating PATCH/POST (existing).
- Long-running mutators: optional `Idempotency-Key` header (reserved; wire in M2-03/M4).

## Job / run status vocabulary

`PENDING` | `RUNNING` | `SUCCEEDED` | `FAILED` | `CANCELLED` | `INTERRUPTED`

## Async operations

Do not hold HTTP open for FDD/import/report. Poll:

- `GET /api/fdd/status`
- `GET /api/jobs/{job_id}/runs/{run_id}`

## Feature flag

`OPENFDD_REACT_UI=1` advertises `capabilities.react_ui: true` (default off). React remains default product UI in Phase 1.

## TypeScript types

See `frontend/web/src/api/contract.ts` (added in P1-M2-02; shape mirrors this document).
