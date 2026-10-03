# PR protocol (Milestone A)

Every pull request follows this loop. Prefer **one architectural purpose** per PR.

Branch naming:

```text
milestone-a/00-architecture-contract
milestone-a/01-release-manifest
milestone-a/02-shared-contracts
milestone-a/03-rule-manifest
milestone-a/04-vibe19-oracle-cutover
milestone-a/05-vibe19-reporting-cutover
milestone-a/06-vibe20-ecm-scheduling
milestone-a/07-vibe20-ecm-bins
milestone-a/08-delete-ecm-twins
milestone-a/09-final-audit
docs/openfdd-agent-spec   # docs-only OK
```

---

## Steps

1. **Sync** — `git fetch --prune`; switch `master` (open-fdd) or `develop` (playground); `pull --ff-only`. Do not destructive-reset unrelated dirty work.
2. **Read** — root `AGENTS.md`, this spec, applicable skills, nearby `AGENTS.md`.
3. **Inspect** — `git log -15`; `gh pr list`; `gh run list --limit 20`. Do not duplicate open work.
4. **Bound the PR** — in-scope / out-of-scope / acceptance / tests / docs.
5. **Branch** — `git switch -c milestone-a/<work>`.
6. **Test-first migration** — inventory → characterize → implement shared → parity → cutover → delete twin → regression → docs.
7. **Validate locally (hard gate before push)** — catch easy failures **before** GitHub Actions:
   - Rust product change: `cargo fmt --check`, `cargo clippy -p <crate> -- -D warnings`, `cargo test -p <crate>` (plus `--test preauth_disclosure` when MT/auth touched).
   - SPA change: `cd frontend/web && npm test -- --run` (and `npm run typecheck` when types changed).
   - Security/qualification Python: `python3 -B -m pytest tests/security -q` and/or `tests/qualification` as touched.
   - Docs-only: link/path sanity; no need for full cargo.
   - Do **not** open or undraft a PR until local targeted tests are green. Actions are the second line, not the first.
8. **Commit intentionally** — focused messages (`feat`, `fix`, `test`, `docs`, `refactor`).
9. **Draft PR** — `gh pr create --draft` with body template below. Include the **local verify commands + results** in the Tests section.
10. **Watch Actions** — `gh pr checks --watch`; classify failures; fix code-owned issues. Prefer cheapest watch model; escalate design failures to a stronger model.
11. **CodeRabbit** — classify comments; fix actionable; reply; do not violate architecture.
12. **Ready + merge** — `gh pr ready`; prefer squash unless repo policy differs; delete branch.
13. **Refresh dependents** — bump playground pins; separate playground PR; GHCR refresh per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).

---

## Agent takeover (single IDE)

When another agent (Codex, cloud worker, etc.) is **out of API budget**, stalled, or the operator asks for one IDE to own the train:

1. **Take over** the open branch/PR — do **not** leave it excluded forever and do **not** open a competing parallel PR on the same files.
2. Prefer the existing worktree (e.g. `.worktrees/<name>/`) or `git fetch` + checkout of the PR head.
3. Finish remaining commits with the same PR purpose; undraft when local verify + Actions are green.
4. Record the takeover in `SESSION_LOG.md` and the PR body (“Cursor took over from …”).
5. Soft-OPEN external blockers (e.g. Nessus license) stay Soft-OPEN — still merge tooling that is complete.

---

## Ops patch cycle (platform closeout)

When driving a **tiny-rev / ops closeout** (not Milestone A migration PRs):

1. **Log first** — gate FAIL → row in [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) **Patch cycle — Phase 7 bugs** + `SESSION_LOG.md` one-liner on milestone events.
2. **One concern per PR** — harness fixes, product fixes, and docs-only fixes stay separate.
3. **VERSION** — bump workspace patch only when product/runtime behavior changes (`docs/VERSIONING.md`).
4. **Auth / MT security PRs** — update [`skills/openfdd-mt-security/SKILL.md`](skills/openfdd-mt-security/SKILL.md) + AGENTS rule **60b** when changing pre-auth routes, tenant ACL, CSP/`security.txt`, or MQTT ACL notes. Keep `cargo test -p openfdd-central --test preauth_disclosure` green.
5. **Post-merge** — GHCR publish → backup + re-pin (Railway + local) → smoke → re-stress affected gate only. **Skip Railway re-pin while Kali owns the hub** unless operator OK.
6. **Railway F1** — cloud pipeline stress (DF55, BUILDING_50, AFDD flood, bldg2) is logged under BUG_REPORT **Railway F1**; it does not block declaring local synthetic CSV FDD evidence.

Full gate matrix: [`scripts/nightly-ot-bench/README.md`](../scripts/nightly-ot-bench/README.md).

## PR body template

```markdown
## Purpose

## Architecture impact

## Changes

## Tests

Local (must be green before push/undraft):
```
<exact commands run>
```
Result: PASS / FAIL (fix before open)

## Cookbook impact

## Packaging impact

## Container impact

## Compatibility and migration

## Known non-goals

## Acceptance checklist
- [ ] Targeted tests pass
- [ ] Broader affected suite pass
- [ ] Docs match code
- [ ] No duplicate canonical modules left active (or exception documented)
- [ ] CodeRabbit actionable threads resolved
```

---

## Failure classes

```text
CODE_FAILURE
TEST_FAILURE
PACKAGING_FAILURE
DOCS_FAILURE
COOKBOOK_PARITY_FAILURE
CONTAINER_BUILD_FAILURE
FLAKY_INFRASTRUCTURE
UNRELATED_BASE_BRANCH_FAILURE
```

One documented rerun for apparent infra flakes; if it repeats, diagnose.
