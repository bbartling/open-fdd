# Async operations substrate (P1-M2-03)

React must **not** hold HTTP open for FDD runs, package import, or reports.

## Status vocabulary (jobs runs)

Canonical strings used by `services/central/src/jobs.rs`:

| status | meaning |
| --- | --- |
| `QUEUED` | accepted, not started |
| `RUNNING` | in progress |
| `SUCCEEDED` | terminal ok |
| `FAILED` | terminal error (incl. restart recovery from interrupted RUNNING) |
| `CANCELLED` | terminal cancel |
| `STALE` | superseded / abandoned |

## Poll contract

| Operation | Create | Poll | Cancel |
| --- | --- | --- | --- |
| Job FDD run | `POST /api/jobs/{job_id}/runs` | `GET /api/jobs/{job_id}/runs/{run_id}` | prefer new cancel when wired; until then mark FAILED/CANCELLED via run update if authorized |
| Registry FDD | `POST /api/fdd/run` | `GET /api/fdd/status` | best-effort; treat timeout as retryable client-side |
| CSV package | `POST /api/csv/import/*` | response or follow-up dataset GET | abort upload stream |

## Client helper

`frontend/web/src/api/asyncOps.ts`:

- `pollUntil(fn, { intervalMs, timeoutMs, isTerminal })`
- classifies `ApiClientError.retryable` for backoff
- never uses long-lived fetch for the operation itself

## SSE / WebSocket

Deferred. Polling is the Phase 1 contract; event shape reserved:

```json
{ "op_id": "...", "status": "RUNNING", "stage": "fdd", "progress": 0.4, "request_id": "..." }
```
