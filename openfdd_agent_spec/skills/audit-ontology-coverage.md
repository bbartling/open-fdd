---
name: audit-ontology-coverage
description: Audit modeling requirements against pinned Brick / ASHRAE 223P / Haystack snapshots and inventory the terms a building graph uses (open-fdd-ontology-audit). Offline and read-only; NF optional.
---
# Ontology coverage audit and model doctor (`pip install "open-fdd[ontology]"`)

Issue #1569. Tool list: `docs/pypi-agent-tools.md`. Nothing here assigns rules, rebinds sensors or writes NF tags.

**Standalone (default, no NF):**

1. Requirements sheet (CSV / XLSX): `category, requirement, description, candidate_URI, vocabulary, reviewer_notes`
   (CURIEs such as `brick:Air_Handling_Unit`, `s223:Duct`, `phIoT:ahu` are fine). Start from
   `open-fdd-ontology-audit --example --out r` (synthetic sheet + two-SAT-sensor AHU graph).
2. Sources: `open-fdd-ontology-audit req.xlsx --refresh --out r` once (downloads the pinned Brick 1.5.0, 223P and
   Haystack 4 defs, sha256-checked, into `~/.cache/open-fdd/ontologies`; never commit them). Later runs are offline.
   Own ontology files: `--ontology FILE` or drop them in `--ontology-dir`.
3. Read the statuses honestly: `VERIFIED_TERM` = the URI is declared in that snapshot, not that it means what the
   requirement says. `CANDIDATE_REVIEW` = label match only. `MAPPING_REVIEW` = namespace right, term absent (often a typo).
   `EXTENSION_REVIEW` = no standard term or an Open-FDD term. `SOURCE_UNAVAILABLE` = not checked, never "missing".
4. Doctor a graph: `open-fdd-ontology-audit --graph building.ttl --shacl --out r` writes `doctor.md/json`, `terms.csv`
   (standard / open-fdd / site-specific, defined / undefined / unchecked), identity and history problems, explicit
   `ofddRole` bindings (two sensors on one role stay two points) and competency query results. `--shacl` needs
   `open-fdd[ontology-shacl]`.

**Optional, NF box** (`open-fdd[nf]`, read-only credentials as in `pypi-nf-agent`): `--from-nf [--app lite]` reads the
app's `rdf` hook and saves `nf_model.ttl` in the report folder. That is a consumer of the NF export, not a second producer.

Change the example graph only by editing `tests/fixtures/ontology_audit/two_sat_ahu_model.json` and regenerating with
`node tools/rdf-check/gen_ttl.js` (a test fails on drift). Tests: `pytest tests/test_ontology_audit.py`.
