---
name: Next rev GHCR refresh train (post-3.5.65 audit)
overview: "One Cursor train after Grok Soft-OPEN on sha-215e159 / 3.5.65: execute next_patch security/RDF/SPARQL/memory/CAMBER work in bounded PRs, keep VERSION↔Cargo↔GHCR pin coherent, local-verify + cargo clean each tip, single final patch bump + GHCR refresh. Grok owns live stress in parallel."
todos:
  - id: n0-intake
    content: "N0 Intake — preserve dirty primary; record master/VERSION/GHCR pin; read private audits + CAMBER handoff; reconcile Grok comments into worklist (no issue close without evidence)"
    status: completed
  - id: n1-security
    content: "N1 Security controls — private SECURITY_AUDIT S01–S09; real middleware/storage tests; #1130–#1132 dispositions"
    status: in_progress
  - id: n2-evaluator
    content: "N2 Evaluator integrity — QUALIFICATION_AUDIT false-PASS counterexamples → permanent regressions"
    status: in_progress
  - id: n3-memory
    content: "N3 #1127 finish — MEMORY_1127 gaps (admission/bytes/cancel/MQTT/receipts/cgroup); no close without combined qual"
    status: pending
  - id: n4-rdf-consumers
    content: "N4 RDF semantics + real FDD/history/ECM consumers — RDF_AUDIT; hold #997/#1002/#1123 until evidence"
    status: pending
  - id: n5-sparql-ui
    content: "N5 SPARQL editor/API — MappingPage panel + POST /api/model/sparql/query read-only SELECT/ASK"
    status: pending
  - id: n6-camber
    content: "N6 CAMBER cross-check — rule tuning, versioned export, M&V vectors, findings adapter (no Camber in GHCR)"
    status: pending
  - id: n7-docs-agent-spec
    content: "N7 Docs/MILESTONES/openfdd_agent_spec — honest status; skills sync; VERSIONING tip table current"
    status: pending
  - id: n8-hygiene
    content: "N8 Hygiene — merge tips; no stale PRs/branches; cancel redundant Actions; cargo clean / wipe worktree target/"
    status: pending
  - id: n9-release-ghcr
    content: "N9 FINAL — one tiny patch bump (3.5.65→3.5.66 if still next) + VERSION/Cargo sync → merge → GHCR → pin newest-by-created sha-* → Grok re-stress handoff"
    status: pending
isProject: true
---

# Next rev GHCR refresh train (2026-10-05)

**Status:** EXECUTING. Grok Soft-OPEN on prior tip runs **in parallel** — do not fight their deploy. Cursor ships the next patch train to a **new** tip.

## Read first (do not skip)

1. Detail plan (P0–P7): [`.cursor/plans/next_patch_security_rdf_sparql_memory_20261005.plan.md`](next_patch_security_rdf_sparql_memory_20261005.plan.md)
2. Private audits (outside git): `/home/ben/Documents/Codex/private_audits/openfdd_20261005_215e159/` — `README.md`, `SECURITY_AUDIT.md`, `RDF_AUDIT.md`, `QUALIFICATION_AUDIT.md`, `MEMORY_1127_AUDIT.md`, `CAMBER_REVIEW.md`
3. CAMBER handoff: [`.cursor/agents/camber-interop-crosscheck-handoff-20261005.md`](../agents/camber-interop-crosscheck-handoff-20261005.md)
4. Spec: root `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `openfdd_agent_spec/docs/VERSIONING.md`, `openfdd_agent_spec/skills/openfdd-stack-ghcr/SKILL.md`
5. Prior closeout handoff: agent-store `docs/grok-handoff-sha-215e159.md`

## Baseline tip (reconcile every session)

| Axis | Value at train open |
| --- | --- |
| Audit / Soft-OPEN tip | `215e1594675e8a6b8a113dc0399950ab649ba2a4` |
| Platform VERSION | **3.5.65** on `origin/master` |
| GHCR pin for Grok now | `OPENFDD_IMAGE_TAG=sha-215e159` |
| Next release bump | **3.5.66** (only if still next at N9 — recheck `origin/master:VERSION`) |
| Dirty primary | `/home/ben/Desktop/open-fdd` may lag (e.g. local `4251505` / 3.5.64) — **do not reset**; worktrees only |

## VERSION ↔ GHCR contract (every rev)

Per `openfdd_agent_spec/docs/VERSIONING.md`:

1. **One** workspace patch bump per GHCR turnkey closeout — root `VERSION` + Cargo workspace `version` stay identical.
2. Do **not** bump mid-train for every tip. Land product PRs at current 3.5.65 until **N9**.
3. At N9: bump `3.5.65` → next available patch → merge → wait stack GHCR publish → pin **newest-by-created** `sha-<7>` (never `:nightly` name sort):
   ```bash
   ./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt openfdd-fieldbus
   # OPENFDD_IMAGE_TAG=sha-<that>
   ```
4. Sidebar / `/api/health` must show `{VERSION}+shortsha` for the running central image.
5. Do **not** bump PyPI `open-fdd` unless Python package APIs changed in this train.
6. Update `openfdd_agent_spec` tip tables / MILESTONES / skills only with evidence (N7); sync skills via `./scripts/openfdd_install_agent_skills.sh --sync` when skills change.

## Local verify + disk (every tip)

- Worktrees under `.worktrees/`; preserve dirty primary.
- One `cargo` at a time on bensbench; after each tip batch: `cargo clean` and/or `rm -rf .worktrees/<tip>/target`.
- No local stack `docker build`. Local = clippy/tests for touched crates + frontend vitest when UI touched.
- Local-first; do not block on `gh pr checks --watch`. Cancel redundant/superseded Actions (merged-branch, duplicate push).
- Never `docker compose down -v`; never delete `workspace/`; never print secrets; cookbooks sacred.

## Wall-clock sequence

```text
N0  Intake + Grok reconcile (while Grok tests)
N1  Security controls          ─┐
N2  Evaluator integrity        ─┤ may parallelize in separate worktrees after N0
N3  #1127 memory finish        ─┤
N4  RDF + real consumers       ─┘
N5  SPARQL UI/API (after N4 foundation)
N6  CAMBER (fit around N1–N4; no live BAS)
N7  Docs / agent_spec / MILESTONES
N8  Hygiene (PRs/branches/Actions/cargo clean)
N9  VERSION bump → GHCR → newest-by-created pin → Grok handoff
```

Map to detail plan: N0=P0 · N1=P1 · N2=P2 · N3=P3 · N4=P4 · N5=P5 · N6=P6 · N7–N9=P7.

## Issue closure (hard)

Close **only** when that issue’s acceptance in the detail plan is met with evidence. Green Actions / HTTP 200 / same broken harness ≠ close. Especially hold: #999, #997, #1002–#1004, #1123, #1127. Reopen or link residual issues if prior CLOSE left unmet behavior (#1000/#1001 noted in audit).

## Success

- Bounded PRs merged for N1–N6 concerns with independent regressions.
- Docs/MILESTONES/`openfdd_agent_spec` honest; skills synced if changed.
- No stale train PRs/branches; `target/` cleaned.
- One new platform tip: **3.5.66** (or next) + `sha-*` newest-by-created documented; Grok re-stress handoff written.
- No FQ claim from this train alone.
