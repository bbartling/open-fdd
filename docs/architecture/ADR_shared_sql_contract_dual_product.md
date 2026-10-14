# ADR: Shared SQL contract — dual product (OSS Rust + private BPS)

**Status:** Accepted Soft-OPEN stub (2026-10-14). Soft-OPEN ≠ FQ.

## Context

Public **open-fdd** (Rust central) and private **BPS** (Python/FastAPI) both run
Timescale SQL FDD. Equations must not fork. Future BPS digital twinning must not
redefine schema, rule IDs, or analytics SQL.

## Decision

1. **One versioned SQL/schema/analytics pack** — pin `contract_version` +
   `pack_sha256` from `sql/contract/manifest.json`.
2. **OSS product API stays Rust** — no full port of central/FDD to FastAPI.
3. **BPS stays private Python** — steals UX/RDF/SPARQL/Plotly patterns; executes
   the same SQL pack.
4. **Twin/IoT layers** sit beside the warehouse; they do not redefine FDD SQL.
5. **Timescale ONLY** — no dual-write / Parquet co-canonical.

## Consequences

Adapters (Rust or Python) bind parameters, enforce auth, and serialize results.
Scientific truth is the hash-pinned SQL pack. Soft-OPEN evidence ≠ FQ.
