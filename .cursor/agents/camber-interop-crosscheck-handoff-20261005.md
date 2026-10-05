# Cursor prompt — CAMBER cross-check and Open-FDD contract follow-up

Read and incorporate the CAMBER workstream of:

`/home/ben/Desktop/open-fdd/.cursor/plans/next_patch_security_rdf_sparql_memory_20261005.plan.md`

Read the exact current-source findings, primary references and five interop answers:

`/home/ben/Documents/Codex/private_audits/openfdd_20261005_215e159/CAMBER_REVIEW.md`

The review is against Open-FDD 215e159 / 3.5.65 and CAMBER v0.99.1 source 1d877ce9. CAMBER's published G36 comparison used Open-FDD 32a6d447 / 3.5.58 / PyPI 4.4.9. Recheck latest master and preserve active work before implementation. Keep original and new versioned results separate.

Implement focused Rust regression tests and fixes for explicit EPS_SAT precedence, effective FC9/11/14/15 sensor-tolerance wiring, equation/FC13 state boundaries justified against a named G36 edition, individual equipment input-readiness and per-equipment minimum-OA commissioning evidence. Do not hardcode LBNL units, a campus or equipment label. Keep production Rust and externally documented pandas oracle behavior coordinated without embedding Python/CAMBER in central.

Create one authorized, versioned native JSON/package export contract for explicit site IANA timezone, timestamp encoding, per-point kinds/units/command representation, equipment stamps/topology, role crosswalk and weather map. Do not promise internal tenant Parquet paths as stable by accident, infer circuit roles from names, or turn a binary command into measured speed/status. Roundtrip legacy, mixed-unit, DST, ambiguous-role and two-tenant fixtures with revision provenance.

Consume pinned small synthetic M&V vectors through files, with independent hand-derived statistics/predictions/savings checks. Keep calibration and regression-baseline policies distinct; record purpose, edition, interval, fitting grid/selection, sign/deadband, weights, degrees of freedom, fit/holdout, extrapolation and uncertainty. CAMBER expected results are a comparator, not the only truth. Missing optional real-data tiers remain explicitly not run; require hashes/licensing and a budget before publisher-data downloads.

Review findings JSON as a draft external file adapter preserving each engine's version, input/config/model identity, evaluated hours, denominator, evidence and declined/unknown states. No merged verdict or automatic control binding. Update canonical docs, both equation cookbooks, agent context, milestones and issue/PR links with actual acceptance evidence. Fit this bounded work around the main plan's security/evaluator/memory priorities and Grok findings; no live deployment, stress or BAS write is authorized by this prompt alone.
