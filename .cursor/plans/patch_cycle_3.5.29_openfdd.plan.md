---
name: Open-FDD 3.5.29 patch cycle
overview: "Optimized 3.5.29 cycle: hygiene → security Python harness (offline HOLD deploy) → Soft-OPEN tip → GHCR → Railway+fieldbus+DIY BACnet@38400 → MEGA hub stress (incl. gates 25/25b/26) → BUG_REPORT + hygiene end. No stale PRs/branches; no mid-wave stress; no local docker build."
todos:
  - id: p0-hygiene-start
    content: "GH hygiene START — 0 open PRs; tip Actions green; hub healthy; prune stale branches"
    status: completed
  - id: sec-plan-fold
    content: "Fold security_stress_integration_audit into this plan + sub-checklist"
    status: completed
  - id: sec-inventory
    content: "Security route inventory + policy/fixture manifests (BLOCKED≠PASS)"
    status: pending
  - id: sec-harness
    content: "Python openfdd_security lib/CLI + offline A/B evaluators (HOLD live deploy)"
    status: pending
  - id: sec-gates
    content: "Wire gates 25/25b/26 stubs; repair legacy false-PASS; manifest profile validator"
    status: pending
  - id: p1-pick-fix
    content: "Pick ONE Soft-OPEN / product fix for tip (after sec offline + hub audit)"
    status: pending
  - id: p2-version
    content: "VERSION bump 3.5.28 → 3.5.29 (+ Cargo/README)"
    status: pending
  - id: p3-implement
    content: "Ship tip fix + security tooling (one or two focused PRs; merge green)"
    status: pending
  - id: p4-pr-merge
    content: "PR squash-merge → GHCR Publish; delete branch; 0 open PRs"
    status: pending
  - id: p5-tip-gate
    content: "./scripts/check_ghcr_tip_stack.sh sha-<7> PASS"
    status: pending
  - id: p6-backup-repin
    content: "Backup then Railway hub re-pin central→mqtt→web to tip"
    status: pending
  - id: p7-fieldbus-bacnet
    content: "Fieldbus tip + ACME ingest; local BACnet@38400 DIY/FEC bench if picked"
    status: pending
  - id: p8-mega-stress
    content: "MEGA hub stress LAST — FQ; 19+35; 25/25b; mqtt ACL 26 if applicable; synth59 59/59"
    status: pending
  - id: p10-bug-report
    content: "BUG_REPORT_WAVE_P tip + security scope + stress cites"
    status: pending
  - id: p11-hygiene-end
    content: "GH hygiene END — 0 open PRs; tip Actions green"
    status: pending
isProject: false
---

# Open-FDD 3.5.29 patch cycle (optimized + security mega-stress)

> **For agentic workers:** Execute in the order below. Do **not** stress mid-wave. Do **not** local `docker build` on bensbench. **No stale open PRs / feature branches / unexplained failed Actions.**

**Goal:** Ship `3.5.29` with (1) reusable Python security regression harness + truthful qualification wiring, (2) one Soft-OPEN/product tip fix, (3) Railway + fieldbus refresh, (4) DIY MS/TP@38400 local OT when applicable, (5) **MEGA** hub stress FQ including new security phases.

**Sub-plan (acceptance checklist):** [`.cursor/plans/security_stress_integration_audit.md`](/home/ben/Desktop/open-fdd/.cursor/plans/security_stress_integration_audit.md) · agent brief [`.cursor/agents/openfdd-security-python-harness.md`](/home/ben/Desktop/open-fdd/.cursor/agents/openfdd-security-python-harness.md)

**Baseline:** OPS PINNED **`3.5.28` / `sha-4a5c11e`** · prior FQ `reports/nightly-ot-bench_20260917T215437Z/` · tracker `docs/operations/BUG_REPORT_WAVE_P.md`

**HOLD during security offline work:** No Railway re-pin / live hub mutation / OT writes / secret fetch solely for harness build. Live gates 25/25b execute only in **Task MEGA stress** after tip pin.

---

## Optimized order (speed)

| Phase | Master todos | Parallel? | Deploy? |
|-------|--------------|-----------|---------|
| **A. Hygiene** | `p0` | — | no |
| **B. Security offline** | `sec-inventory` → `sec-harness` → `sec-gates` | inventory∥early lib skeleton | **HOLD** live |
| **C. Tip pick + ship** | `p1` → `p2` → `p3` → `p4` → `p5` | CI wait only | GHCR publish yes |
| **D. Hub refresh** | `p6` → `p7` | fieldbus after central healthy | Railway + local fieldbus |
| **E. MEGA stress LAST** | `p8` | — | live hub yes |
| **F. Closeout** | `p10` → `p11` | — | no |

### Soft-OPEN candidates (`p1` — pick ONE after Phase B)

| ID | Kind | Notes |
|----|------|-------|
| **security-harness-ship** | Tooling | Prefer if Phase B lands cleanly — tip = harness + gate wiring (+ tiny product fix only if required) |
| **acme-oa-t-dup-reject** | Ops/catalog | ACME duplicate `oa_t` historian rejects |
| **local-bacnet-ot-bench** | Bench | DIY dual-mini + FEC @38400 now available |
| Product bug from hub / BUG_REPORT | Product | One concern only |

---

### Task 0 — Hygiene start (`p0`)

**Exit:** 0 open PRs; only `master` locally (or intentional tip branch); tip Actions green; hub health ok.

- [x] `gh pr list --state open` → empty (2026-09-18)
- [x] Prune local branches with gone remotes (`docs/wave-s-s5-stress-cite`)
- [x] `gh run list --branch master --limit 20` — tip `4a5c11e` Actions green
- [x] Hub health: `ok`, `3.5.28+4a5c11e50b92`, edges=1, ingest live

---

### Task S0 — Fold security sub-plan (`sec-plan-fold`)

- [x] Reference audit plan + agent brief from this plan
- [ ] Keep audit checklist boxes updated as work lands (do not mark live stress done early)

---

### Task S1 — Inventory (`sec-inventory`)

**Exit:** Checked-in route/policy inventory; unknown policy = BLOCKED disposition, not encoded-as-correct.

- [ ] Derive route/method inventory from central registrations
- [ ] Fixture/policy manifests (A/B canaries, roles, nonexistent-object control)
- [ ] CI detection stub for new routes without disposition

---

### Task S2 — Python harness offline (`sec-harness`) — HOLD deploy

**Exit:** `scripts/security/openfdd_security/` + `openfdd_security_probe.py`; dry-run default; offline A + broken-fixture B evaluators PASS/FAIL as specified in audit §5; no Railway traffic.

```bash
python3 scripts/security/openfdd_security_probe.py --list-suites
python3 scripts/security/openfdd_security_probe.py \
  --config scripts/security/examples/fixtures.example.json \
  --base-url http://127.0.0.1:18080 --profile isolated_full --dry-run
# Offline unit/evaluator suite (exact entrypoint per README)
```

Profiles: `live_readonly` | `isolated_full` | `local_open`. See audit §3 for budgets/TLS/redirect/privacy rules.

---

### Task S3 — Gates + legacy repairs (`sec-gates`)

**Exit:** Offline orchestrator sabotage tests green; runners *wired* for 25/25b (26 when broker suite applicable) but **not executed live** until Task MEGA; legacy 401-as-authz / Wave L fabricated PASS / shared artifact names repaired or labeled limited smoke.

- [ ] `25_security_python_harness` precheck + `25b_security_post_stress` postcheck in `run_railway_hub_stress.sh` / `run_all.sh`
- [ ] `26_security_mqtt_acl` optional-feature wiring (BLOCKED≠continuity PASS)
- [ ] Repair gates 07/20/22/23 false-PASS paths per audit §1
- [ ] Manifest profile/evidence validator; dry-run/stale/hash mismatch ⇒ not FQ

---

### Task 1 — Pick tip fix (`p1`)

**Decision:** _(pending)_

- [ ] Re-read Soft-OPEN in `BUG_REPORT_WAVE_P.md`
- [ ] Prefer shipping security harness as tip content if Phase B complete; else one Soft-OPEN id
- [ ] Write decision paragraph here

---

### Task 2–4 — VERSION → implement → PR/GHCR (`p2`–`p5`)

- [ ] Bump `3.5.28` → `3.5.29` (VERSION, Cargo workspace, README tip line)
- [ ] Minimal product/ops diff + security tooling
- [ ] One (or two sequential) green PRs; squash-merge; `--delete-branch`
- [ ] Wait **Publish Open-FDD stack to GHCR** + `./scripts/check_ghcr_tip_stack.sh sha-<7>` PASS
- [ ] Confirm `gh pr list --state open` empty after merge

---

### Task 5–6 — Container refresh (`p6`–`p7`)

```bash
env -u RAILWAY_TOKEN ./scripts/railway_central_workspace_backup.sh
env -u RAILWAY_TOKEN OPENFDD_IMAGE_TAG=sha-<7> ./scripts/railway_repin_hub.sh
env -u RAILWAY_TOKEN ./scripts/openfdd_fieldbus_railway_up.sh sha-<7>
# Local BACnet @38400 DIY/FEC when Soft-OPEN local-bacnet picked:
# scripts/ops/local_bacnet_ot_bench.sh …
```

---

### Task MEGA stress LAST (`p8`)

```bash
env -u RAILWAY_TOKEN -u OPENFDD_ADMIN_PASSWORD ACCEPT_ZAP_MEDIUM=1 \
  ./scripts/nightly-ot-bench/run_railway_hub_stress.sh
```

**Exit (enhanced):**
- `SUMMARY.md` Status **PASS**, `fully_qualified=true`
- Gates **19** + **35** PASS
- Gates **25** + **25b** PASS (or profile-justified N/A with evidence — never dry-run as PASS)
- Gate **26** PASS/BLOCKED per broker profile (never continuity-as-security)
- Synth59 OpenFDD SQL **59/59**
- Manifest shows `security_scope` + coverage counts; candidate sha matches tip

---

### Task Closeout (`p10`–`p11`)

- [ ] `BUG_REPORT_WAVE_P.md` → OPS PINNED 3.5.29 / sha; backup; stress path; Soft-OPEN closes; security harness cite
- [ ] 0 open PRs; tip Actions green; master TODOs completed/cancelled with reason

## Anti-patterns

- Mid-wave Railway stress or citing old FQ for new tip
- Local docker/cargo image builds on bensbench
- Live security execute during Phase B HOLD
- 401-as-authorization PASS; missing creds as N/A; Wave L OFF suite fabricated PASS on MT hub
- Stale open PRs / leftover feature branches after merge
- Pi fieldbus as Railway closeout path

## Done when

All master todos completed/cancelled; hub `3.5.29+…`; MEGA FQ cited; security offline checklist in audit plan checked; 0 open wave PRs.
