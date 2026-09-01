# Rule display names — single contract

Operators see the same FDD rule under different labels today. This doc defines **one naming contract** across docs, API, and React surfaces.

## Problem (2026-09-01)

| Surface | Example (FC1) | Source today |
| --- | --- | --- |
| Cookbook heading | `FC1 — Duct static below SP at full fan (GL36 A)` | `docs/rules/cookbook/datafusion-sql-cookbook.md` |
| Registry / API | `description: Duct static below SP at full fan` | `sql_rules/registry.yaml` |
| Left rail (Rule tuning) | `FC1 — Duct static below SP at full fan` **truncated to 36 chars** | `RuleTuningPanel` summary |
| FDD Plots rule `<select>` | `FC1 — Duct static below SP at full fan` (full) | `ReportsPage` + `GET /api/fdd/rules` |
| Plot title (center) | `FC1 · AHU_1` (id only) | `vibeCharts.ruleResultChart` |
| Health matrix column | `FC1` (header); tooltip via `healthColumnHeader` | `HealthMatrixSection` + partial `cookbookRuleCatalog.ts` |
| Findings / CSV export | `title` column when present | `fddApi.resultsToCsvArtifact` |

**Goal:** one formatter, three tiers of name length, zero drift between registry and cookbooks.

## Authority order

1. **`rule_id`** — stable machine key (never rename without migration).
2. **`description`** in `sql_rules/registry.yaml` — **short display name** (sidebar, dropdowns, matrix tooltips, CSV `title`).
3. **Cookbook heading** — long engineering title + optional GL36 / reference suffix; must start with the same short name as registry `description`.
4. **Haystack tags** — optional suffix on health-matrix tooltips only (`healthColumnHeader`).

Do **not** maintain a second hardcoded description map in the SPA except as a **boot-time cache** merged from `GET /api/fdd/rules` (see `frontend/web/src/lib/cookbookRuleCatalog.ts`).

## Display tiers (UI)

| Tier | Function | Use |
| --- | --- | --- |
| **Short** | `{rule_id}` | Plot filenames, compact badges, health matrix column header |
| **Standard** | `{rule_id} — {description}` | Sidebar expanders, FDD Plots rule picker, Run Rules table |
| **Long** | Cookbook heading text (optional GL36 suffix) | Docs, tooltips on “?” icons, WattLab export captions |

Implement once in `frontend/web/src/lib/ruleLabels.ts` (planned):

```ts
export function ruleLabelShort(ruleId: string): string;
export function ruleLabelStandard(ruleId: string, description?: string): string;
export function ruleLabelPlotTitle(ruleId: string, equipmentId: string, description?: string): string;
```

**Plot center window:** prefer `ruleLabelStandard` or `ruleLabelPlotTitle` — not bare `rule_id` alone.

## Surfaces that must call the formatter

| Component | File |
| --- | --- |
| Left rail rule tuning | `components/RuleTuningPanel.tsx` — remove `.slice(0, 36)` truncation |
| FDD Plots rule select | `pages/ReportsPage.tsx` |
| Plotly chart title | `api/vibeCharts.ts` (`ruleResultChart`) |
| Health matrix headers | `components/HealthMatrixSection.tsx` via `healthColumnHeader` |
| Run Rules catalog | `pages/RulesPage.tsx` |
| Findings / Results | any table exporting `rule_id` + human label |

## Docs / CI alignment

When adding or renaming a rule:

1. Update `sql_rules/registry.yaml` (`rule_id`, `description`).
2. Update cookbook heading: `### {rule_id} — {description} (…refs…)`.
3. Update `parity-matrix.md` if parity status changes.
4. Run `python scripts/cookbook_parity_check.py --all` (see [`COOKBOOK_OWNERSHIP.md`](COOKBOOK_OWNERSHIP.md)).

**Future gate (optional):** assert registry `description` equals cookbook short title (text before first ` (`).

## Anti-patterns

- Duplicating descriptions in React without merging from API at startup.
- Truncating standard labels in the sidebar while showing full text in the center panel.
- Using health-matrix `ruleId` strings that do not exist in the registry (e.g. stale flag column keys).
- Generating cookbook text only from OpenAPI with no hand-written engineering expression.

## Tracking

- Closeout plan: `.cursor/plans/3.3.15_closeout_stress_9022f038.plan.md` → `phase7-rule-display-names`
- BUG_REPORT soft-OPEN: `rule-display-name-drift`
- Agent rule: [`AGENTS.md`](../AGENTS.md) §46
