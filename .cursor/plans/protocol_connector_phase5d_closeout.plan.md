# Protocol connector Phase 5D — qualification and closeout

**Branch:** `feat/protocol-connectors-phase5d`
**Stacked base:** `feat/protocol-connectors-phase5` (draft PR #1100)
**Purpose:** finish the bounded connector program with reproducible image,
recipe, synthetic, and read-only bench evidence. This plan authorizes no merge,
production deployment, BAS write, release, or unbounded discovery.

## Preconditions and stop conditions

- [ ] Rebase only after the Phase 5 base is stable; preserve its accepted
  process split and durable receipt contracts.
- [ ] Record the exact source SHA and immutable image digests used by every
  qualification run. A moving tag is never evidence.
- [ ] Halt live BACnet qualification if device instance `5007` is unreachable.
  Do not replace it with a synthetic success or expand discovery.
- [ ] Treat `192.168.204.12` only as a possible Haystack bench host. Obtain the
  exact endpoint, auth mode, and catalog from secure local configuration. If
  they are unavailable, record `BLOCKED` and retain synthetic coverage.
- [ ] Never print, commit, or attach passwords, bearer tokens, SCRAM material,
  cookies, JWTs, or raw credential files.
- [ ] Use read-only BACnet operations. Do not issue WriteProperty, release,
  priority-array mutation, or remediation traffic.
- [ ] Follow root and nested `AGENTS.md`, `openfdd_agent_spec`, the low-RAM
  policy, and the generic data-model rule. Bench identifiers belong only in
  tests and operator commands, never product defaults or runtime branches.

## 5D-1 — make the closeout gate executable

- [ ] Add one bounded qualification entry point with distinct synthetic,
  image/recipe, BACnet-live, and Haystack-live stages. Each stage produces a
  machine-readable result plus a concise Markdown summary.
- [ ] Fail closed on missing commands, authentication failures, wrong process
  ownership, prohibited listeners/routes, receipt mismatches, stale data, or
  historian readback failure. `SKIP` and `BLOCKED` must never count as `PASS`.
- [ ] Add negative evaluator tests proving forged, stale, partial, empty, and
  contradictory evidence cannot produce a qualified verdict.
- [ ] Keep artifacts bounded and sanitized. Include timestamps, source SHA,
  image digests, configuration fingerprints, test counts, and exact failures.

## 5D-2 — immutable images and deployment recipes

- [ ] Build and qualify the distinct `openfdd-bacnet-modbus` and
  `openfdd-haystack` Docker targets in CI. Do not build heavy images locally on
  the low-RAM bench.
- [ ] Inspect image contents and runtime metadata: correct Rust executable,
  non-root user, healthcheck, expected exposed ports, and absence of the other
  connector executable/protocol implementation.
- [ ] Prove cloud recipes start no OT connector. Prove BACnet/Modbus edge and
  Haystack edge recipes start only their selected connector unless an explicit
  documented combined-edge recipe is chosen.
- [ ] Pin qualification recipes to immutable `sha-*` references or digests and
  record resolved digests. Preserve optional MQTTS forwarding; direct local
  historian ingestion must not depend on MQTT.
- [ ] Run Compose config validation and live process/PID/socket checks. A YAML
  declaration alone is insufficient.
- [ ] Use existing repository publication, SBOM, provenance, signing, and
  vulnerability gates where available. Document any unavailable external gate
  honestly rather than weakening it.

## 5D-3 — BACnet read-only bench proof

- [ ] Preflight interface/routing and confirm device instance `5007` using the
  existing trusted device configuration. Halt if unreachable.
- [ ] Preserve any existing fieldbus container and avoid port collisions; use
  the documented alternate-port or isolated-project procedure.
- [ ] Exercise bounded discovery/read, typed point tree, present-value refresh,
  priority-array read, and one scheduled priority-history visit through the
  Rust process and authenticated APIs.
- [ ] Prove no write/release endpoint or packet was used, the visit does not
  overlap, device identity is model/config driven, and persisted history
  survives a controlled process restart.
- [ ] Record packet/request counts and duration so the evidence demonstrates a
  bounded workload rather than merely HTTP success.

## 5D-4 — authenticated Haystack bench proof

- [ ] Load the trusted connector catalog; never accept caller-controlled
  upstream URLs, grids, or arbitrary filters.
- [ ] Exercise the configured Basic or SCRAM flow against the actual bench
  server with bounded `about`, `nav`, current, and history reads.
- [ ] Verify canonical refs, source timestamps, units, scope, row/sample caps,
  redirect refusal, and response-size limits.
- [ ] Deliver one typed envelope to authenticated Central, require an exact
  committed receipt, and query the canonical historian for the same source
  samples and timestamps.
- [ ] Replay the same request identity and prove no duplicate historian rows or
  second payload. Prove changed parameters conflict before an upstream reread.
- [ ] Restart between pending and retry where practical and prove the durable
  payload is resumed. Verify the Haystack process opens no BACnet UDP socket and
  exposes no BACnet/Modbus management routes.

## 5D-5 — operating mode decision

- [ ] Decide and document whether this release supports manual collection only
  or a bounded automatic Haystack schedule. Capability manifests, UI text,
  recipes, and tests must agree.
- [ ] If automatic collection is implemented, use one non-overlapping,
  catalog-driven scheduler with bounded jitter/backoff, durable identity,
  restart recovery, and no catch-up burst. Add clock-controlled tests.
- [ ] If manual-only is retained, advertise manual-only explicitly and leave a
  tracked follow-up; do not imply continuous collection.

## 5D-6 — documentation and PR closure

- [ ] Update the protocol runtime guide, architecture decision record,
  capability ledger, `MILESTONES.md`, and
  `openfdd_agent_spec/SESSION_LOG.md` with exact evidence and limitations.
- [ ] Cross-reference issue #781 and the Phase 5 PR chain. Close #781 only when
  its acceptance criteria are actually represented by committed evidence.
- [ ] Run formatting, clippy with warnings denied, relevant workspace tests,
  React/Compose/security guards, split gate, and evidence-evaluator negatives.
- [ ] Push fixes frequently. Wait for all required GitHub Actions on the exact
  head SHA. Resolve merge conflicts without merging either stacked PR.
- [ ] Final state: both PRs remain open, Phase 5D is mergeable, no failed or
  cancelled required check is presented as success, no stale temporary branch
  or disposable container remains, and all Soft-OPEN items are listed.

## Required closeout evidence

The PR may be marked ready only when its summary links to:

1. exact source SHA and green required Actions;
2. immutable image digests and image/process isolation results;
3. cloud and edge recipe validation;
4. read-only device `5007` evidence, or an explicit blocking record;
5. authenticated live Haystack-to-Central-to-historian evidence, or an explicit
   blocking record;
6. replay/restart and negative evaluator results;
7. documentation/capability updates with no unsupported qualification claim.

Synthetic success is necessary but cannot substitute for either live bench
stage. A blocked external bench stage may leave the draft PR mergeable as code,
but it keeps the corresponding operational qualification Soft-OPEN.

## Cursor continuation handoff

The latest implementation checkpoint is pushed at source SHA
`693509199bdaad779282c307798a49e61725e901` on
`feat/protocol-connectors-phase5d`. If the coding-agent window expires, resume
from that exact SHA and keep PR #1101 open and unmerged. Run the following
before changing product code:

```bash
git status --short --branch
git log --oneline -5
python3 scripts/qualification/protocol_connector_qualification.py --selftest
python3 -B -m unittest discover -s tests/qualification -v
python3 scripts/validate_capabilities_ledger.py
```

Next work is evidence and CI completion: verify the Phase 5C exact-head
review, run the split gate in GitHub Actions with
`OPENFDD_SPLIT_EVIDENCE_DIR`, evaluate its `image_recipe.json`, and retain the
exact Actions run/SHA. Do not run Docker image builds on the low-RAM bench.
For the BACnet stage, first verify the configured read-only device 5007 and
halt with `BLOCKED` evidence if it is unreachable. For Haystack, obtain the
endpoint, catalog, and auth mode only from secure local configuration; never
guess the possible Pi address or print credentials. Use the evaluator's fixed
check IDs and do not mark a stage PASS from HTTP 200 alone.

The final PR body must list exact source SHA, CI run URLs, image IDs/digests,
cloud/edge recipe evidence, live-stage evidence or explicit blockers, and
remaining Soft-OPEN items. Keep the Haystack capability manual-only unless a
separate bounded scheduler implementation and clock-controlled recovery tests
are actually landed. No merge, deployment, GHCR re-pin, BAS write/release,
unbounded discovery, or public issue closure belongs in this closeout PR.
