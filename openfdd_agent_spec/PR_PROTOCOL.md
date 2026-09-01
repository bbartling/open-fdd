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
7. **Validate locally** — smallest tests, then affected suite; clean venv wheel install for packaging.
8. **Commit intentionally** — focused messages (`feat`, `fix`, `test`, `docs`, `refactor`).
9. **Draft PR** — `gh pr create --draft` with body template below.
10. **Watch Actions** — `gh pr checks --watch`; classify failures; fix code-owned issues.
11. **CodeRabbit** — classify comments; fix actionable; reply; do not violate architecture.
12. **Ready + merge** — `gh pr ready`; prefer squash unless repo policy differs; delete branch.
13. **Refresh dependents** — bump playground pins; separate playground PR; GHCR refresh per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).

---

## Ops patch cycle (platform closeout)

When driving a **tiny-rev / ops closeout** (not Milestone A migration PRs):

1. **Log first** — gate FAIL → row in [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) **Patch cycle — Phase 7 bugs** + `SESSION_LOG.md` one-liner on milestone events.
2. **One concern per PR** — harness fixes, product fixes, and docs-only fixes stay separate.
3. **VERSION** — bump workspace patch only when product/runtime behavior changes (`docs/VERSIONING.md`).
4. **Post-merge** — GHCR publish → backup + re-pin (Railway + local) → smoke → re-stress affected gate only.
5. **Railway F1** — cloud pipeline stress (DF55, BUILDING_50, AFDD flood, bldg2) is logged under BUG_REPORT **Railway F1**; it does not block declaring local synthetic CSV FDD evidence.

Full gate matrix: [`scripts/nightly-ot-bench/README.md`](../scripts/nightly-ot-bench/README.md).

## PR body template

```markdown
## Purpose

## Architecture impact

## Changes

## Tests

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
