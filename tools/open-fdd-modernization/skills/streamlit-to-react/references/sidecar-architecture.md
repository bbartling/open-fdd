# React + service-sidecar architecture

## Choose the authoritative backend

Use the repository's target architecture:

| Product goal | Backend pattern |
| --- | --- |
| Retain Python calculations | React + FastAPI calling shared Python modules |
| Remove Python from production | React + Rust/target service; Python is a frozen oracle only |

Do not add FastAPI as a temporary bridge when the migration goal explicitly
removes Python. Temporary APIs tend to become permanent coupling.

## Boundary

```text
Browser
  -> React static application
      -> local UI state
      -> request/cache state
      -> /api requests
          -> authoritative service
              -> validation and authorization
              -> domain services/calculations
              -> files, databases, jobs, reports
```

When Python remains:

```text
Streamlit app ---------+
                       +-> shared Python domain modules
FastAPI routes --------+
```

When Python is retired:

```text
Streamlit/Python -> normalized oracle fixtures only

React -> Rust API -> Rust domain services -> DataFusion SQL/storage
```

The replacement must not expose Streamlit session keys, local server paths, or
Python object shapes as a public contract.

## API conventions

- Prefix product routes with `/api`; define a compatibility/version policy.
- Provide health, readiness, capabilities, and version endpoints.
- Validate the same bounds and choices the UI exposes.
- Return structured raw values; format display text in React.
- Make units, timestamps, timezones, and missing values explicit.
- Use consistent validation/error payloads and request IDs.
- Use durable job/operation endpoints for long-running work.
- Define idempotency, optimistic concurrency, cancellation, and artifact rules.
- Generate or check TypeScript types from the authoritative contract.

## React request behavior

- Read an environment API URL or use same-origin `/api`.
- Debounce continuous controls where the reference behavior permits it.
- Abort or ignore requests made stale by new input.
- Keep input, operation, and result states distinct.
- Show validation errors near responsible controls.
- Distinguish initial load, refresh, empty, offline, permission, conflict, and
  server error.
- Never silently replace server results with demo values in production.
- Keep durable project state on the server, not only in browser storage.

## Deployment

### Separate origins

Expose UI and API on separate hostnames or ports. Configure narrow CORS origins
and an API URL reachable from the user's browser.

### Reverse proxy or same service

Serve React at `/` and proxy or serve `/api` from the authoritative backend.
This reduces CORS complexity. Preserve SPA fallback without swallowing API 404s.

### Containers

- Build React in a pinned Node builder stage.
- Serve static assets from a production web/Rust service.
- Run the backend independently with health/readiness checks.
- Keep secrets out of frontend build variables.
- Verify browser reachability; a container service name is not necessarily
  reachable from browser JavaScript.
- If the target is Python-free, scan the final runtime image/SBOM and test on a
  host where Python is unavailable.

## Migration sequence

1. Characterize the reference with deterministic fixtures.
2. Create normalized oracle output.
3. Define the stable API/error/artifact contract.
4. Implement the authoritative backend.
5. Generate/check the TypeScript client.
6. Build React against stable contracts.
7. Compare semantic, interaction, visual, and artifact behavior.
8. Cut over behind a reversible flag.
9. Retire Streamlit only after acceptance and an observation window.
10. If required, delete Python production dependencies and prove a clean runtime.
