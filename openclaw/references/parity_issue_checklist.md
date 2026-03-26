# Frontend/API parity issue checklist

Use this before filing parity bugs (especially count-sensitive SPARQL issues like `#92`).

## Goal

Separate real product defects from auth drift and runtime graph churn.

## Preflight (must pass)

1. Auth context is healthy for the full run.
   - valid Bearer key
   - no mid-run 401/403
2. Bench endpoints are stable.
   - frontend reachable
   - backend reachable
   - BACnet target reachable (if test depends on it)
3. Record runtime context in `issues_log.md`.
   - API URL
   - frontend URL
   - branch/commit
   - log file path

## Repro sequence (for parity)

1. Run `openclaw/bench/e2e/2_sparql_crud_and_frontend_test.py` with frontend parity enabled.
2. Capture failing query names and mode (file-upload path vs textarea path).
3. Re-run the same query under the same auth context.
4. For count-sensitive queries (`COUNT(...)`, especially `07_count_triples.sparql` and `23_orphan_external_references.sparql`):
   - compare frontend result against two near-time backend snapshots
   - classify as drift if backend snapshots differ and frontend matches one of them

## Classification (required in issue draft)

- **Auth/runtime drift**: key/header failures, launch/env mismatch.
- **Graph churn drift**: count-oriented query changes between immediate backend snapshots.
- **Likely product parity defect**: frontend diverges from stable backend snapshots under healthy auth.

## What to include in GitHub issue (product defects only)

- one minimal repro path
- exact failing query name(s)
- expected vs actual
- why auth drift was ruled out
- evidence pointers (log file + timestamp)
- explicit non-goal statement (what this issue is not about)

## Keep #92 semantics

Issue `#92` is specifically about parity divergence **after auth is healthy**. Do not collapse it into generic auth/runtime instability.
