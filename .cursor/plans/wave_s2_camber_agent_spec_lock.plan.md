> **Wave U child detail** — product Soft-OPEN scheduled **after** the security spine. Do not treat as active master.

---
name: Wave S2 Camber agent_spec lock
overview: "Docs tip — Camber Apache-2.0 lock + ADR for one data-model contract (vocab vs tenant instances) + consumer/route matrix (DM-06). GHCR + smoke only."
todos:
  - id: s2-camber-docs
    content: Camber reference in ARCHITECTURE + pypi-oracle skill + SESSION_LOG
    status: pending
  - id: s2-adr
    content: ADR_data_model_graph.md (shared vocab vs instances; vendor≠tenant)
    status: pending
  - id: s2-route-matrix
    content: Consumer/route matrix SPA/central/edge/MCP/exports (DM-06)
    status: pending
  - id: s2-version-pr
    content: VERSION bump docs tip PR merge
    status: pending
  - id: s2-ghcr-smoke
    content: GHCR tip + Railway re-pin + smoke (not FQ)
    status: pending
isProject: false
---

# Wave S2 — Camber lock + data-model ADR

Parent: Wave S master. After S1 OPS PINNED. Enables S5.

## Does

1. Document [Camber](https://github.com/yroussev/camber) (Apache-2.0) as external PyPI-oracle reference — not product runtime.
2. ADR: shared vocabulary vs tenant instance models; vendor grants ≠ manufacturer names; Parquet/DataFusion for telemetry/FDD; RDF/SPARQL for relationships; export TTL vs TriG; namespace choice (`urn:openfdd:ns#` vs commissioning URL).
3. Consumer/route matrix for model JSON/TTL/SPARQL/MCP (honest unavailable where central lacks `/api/model/sparql`).
4. M&V UI policy already in agent_spec (Metering / new radio).

## Stress

Smoke only. No FQ MEGA.
