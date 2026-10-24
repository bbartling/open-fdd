---
name: openfdd-stress-closeout
description: >-
  Current NF/CSV portal qualification, scoped stress evidence, semantic known-answer
  tests, isolated authenticated ZAP and honest closeout reports.
---

# Stress closeout — portal stack

Current product is Rust central, React web, Timescale and NF portal pull/CSV.
MQTT/BACnet/Modbus/Haystack transport containers are archived and unqualified;
Haystack semantic modeling remains active. Historical3.x OT closeout rows do not
qualify the portal product and do not authorize deployment or live scans.

## Tiers

1. Offline: tests/evaluator controls, no application or scanner qualification.
2. Owned isolated candidate: digest-pinned portal stack + NF emulator, synthetic
   tenants, actual data readback, role/lifecycle controls, restore and authenticated
   ZAP. Never restore OT merely to satisfy an old gate.
3. Separately authorized live review: bounded read-oriented app checks. Active
   scans, load bursts and destructive mutations require their own concrete scope.

Read [qualification entry](../../../scripts/qualification/README.md),
[stress contract](../../../scripts/stress/README.md),
[semantic verifier](../../../scripts/qualification/semantic/README.md) and
[ZAP limits](../../../scripts/qualification/zap/README.md).

## Order and evidence

- Establish actual source/image/schema/SQL/model identity and fixture hashes.
- Run the smallest local checks before any push/PR. Python/pandas/RDFLib stays
  tooling-only; no local heavy product builds on bensbench.
- Execute offline qualification/security tests and semantic broken controls.
- Use one container/scanner runner at a time; independent source/test-review
  agents may collaborate without starting duplicate workloads.
- Stress child exit zero is insufficient: v2 evidence needs run nonce, scope,
  script digest, required check IDs, real assertion/comparison counts and matching
  health candidate when --expected-version is supplied. Missing/empty/truncated
  evidence cannot pass. Fixed300second oracle cannot qualify irregular/COV data.
- A denied viewer write is an authorization control, not a successful CRUD test.
  Require exact scoped identity and own-object positive controls plus the complete
  required viewer assertion set. Verify before/after sample/model state.
- Parse RDF and run bound SPARQL known answers. Prefix/text presence, a sparse
  fallback graph, or alias-based charts do not prove semantic readiness. Keep
  fixture verifier PASS separate from a real candidate-export result.
- ZAP negative control must observe the exact injected bad credential receiving
  actual JSON401/403 on all nonce probes. Accepted credentials, missing evidence
  and unrelated scanner errors cannot become PASS. Unknown counts remain null.
- ZAP currently enforces wall time but request counts are post-HAR checks;
  preventive traffic controls and disposable ownership proof are separate needs.
  Keep the documented credential-site compatibility gap visible; never broaden
  bearer scope or disable auth to obtain green.
- Preserve redacted artifacts with hashes. Verify integrity after any redaction;
  never mutate a hashed report and keep its original passing verdict silently.
- Retain FAIL/BLOCKED/NOT_RUN and candidate-specific limitations. Soft-OPEN is
  not FQ; scanner skip or zero numerical comparisons cannot close a release.
- Append reports/checkpoints frequently. Do not rewrite historical passes,
  automatically close issues, rotate secrets, deploy, or publish security details.

## Skill source

Author only openfdd_agent_spec/skills. Repository vendor folders are sync targets,
not second authoring copies. Use scripts/openfdd_install_agent_skills.sh --sync
when those symlinks need refreshing; do not install into home directories unless
requested. See [security skill](../openfdd-mt-security/SKILL.md).
