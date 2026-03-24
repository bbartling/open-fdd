---
title: Issue draft - SPARQL parity mismatch on count-oriented queries
parent: Appendix
nav_order: 21
---

# Issue draft - SPARQL parity mismatch on count-oriented queries

Repo target: `bbartling/open-fdd`

## Proposed title

Data Model Testing frontend/API parity still diverges on count-oriented SPARQL queries even after auth is healthy

## Summary

The overnight bench run showed a real frontend/API parity failure in the SPARQL/Data Model Testing flow.

Some earlier failures were inflated by intermittent backend auth drift, but even after auth was restored the parity suite still reported a smaller set of repeatable mismatches on count-oriented queries.

## Main affected queries seen in overnight evidence

- `07_count_triples.sparql`
- `23_orphan_external_references.sparql`

## Why this issue should stay separate from auth drift

The overnight log contained two layers of failure:

1. early parity API re-fetch failures caused by `401 Missing or invalid Authorization header`
2. later parity mismatches that still remained after authenticated backend access was healthy again

This issue draft is about the second layer only.

## Overnight evidence summary

- Selenium passed
- BACnet discovery passed for fake devices `3456789` and `3456790`
- SPARQL CRUD + frontend parity still failed with exit code 1
- count-style queries showed API vs frontend result differences even in the healthier later run

## Repro direction

1. Run the bench with healthy backend auth for the full parity run.
2. Execute:
   - `2_sparql_crud_and_frontend_test.py --api-url ... --frontend-url ... --frontend-parity`
3. Focus on:
   - `07_count_triples.sparql`
   - `23_orphan_external_references.sparql`
4. Compare API/reference bindings vs frontend file-upload and textarea results.

## Expected behavior

Frontend query execution should match the backend reference result for the same graph state.

## Actual behavior

The frontend path and backend reference path can diverge on count-sensitive queries, which undermines confidence in Data Model Testing parity.

## Hypothesis

This may be related to graph-state timing, stale frontend state, or the same graph-hygiene / orphan-node drift seen elsewhere on the bench.
