# Legacy repo: `bbartling/open-fdd-automated-testing`

**Status:** **Deprecated.** All reusable testing, operator context, and OpenClaw runbooks now live **inside** [bbartling/open-fdd](https://github.com/bbartling/open-fdd) under `openclaw/` and top-level `docs/`. Do **not** treat the old repo as a second source of truth—forks and bookmarks should move here.

**What to do instead**

1. Clone **open-fdd** and `cd` into the repo root.
2. Read **`openclaw/HANDOFF_PROTOCOL.md`** → **`openclaw/SKILL.md`** → **`openclaw/references/testing_layers.md`**.
3. For long queued lab work, use **`openclaw/references/long_run_lab_pass.md`** (paste block) and **`openclaw/issues_log.md`**.
4. Product + operator docs: **`docs/openclaw_integration.md`**, **`docs/operations/`**, **`config/ai/operator_framework.yaml`**.
5. Install the lab skill for OpenClaw: **`openclaw/references/skill_installation.md`**.

**README snippet for the old repository (maintainers):** add at the top of `open-fdd-automated-testing/README.md`:

```markdown
> **Deprecated:** This repository is frozen. Canonical lab, bench harness, and OpenClaw directions live in **[bbartling/open-fdd](https://github.com/bbartling/open-fdd)** under **`openclaw/`** (see **`openclaw/references/legacy_automated_testing.md`** for a full path map). Use that repo only.
```

---

## Path map (old → open-fdd)

| Legacy (`open-fdd-automated-testing`) | Canonical in **open-fdd** |
|---------------------------------------|---------------------------|
| `README.md` (lab overview) | `openclaw/README.md` + root `README.md` (OpenClaw section) |
| `issues_log.md` | `openclaw/issues_log.md` |
| `operator_framework.yaml` | `config/ai/operator_framework.yaml` |
| `docs/**` | `docs/**` (same topical layout: concepts, bacnet, howto, operations, appendix) |
| `docs/operations/openclaw_context_bootstrap.md` | `docs/operations/openclaw_context_bootstrap.md` |
| `docs/operations/testing_plan.md` | `docs/operations/testing_plan.md` |
| `fake_bacnet_devices/` | `openclaw/bench/fake_bacnet_devices/` (bench); see also `scripts/fake_bacnet_devices/` for stack-adjacent scripts |
| `sparql/` | `openclaw/bench/sparql/` |
| `rules/` (lab copies) | `openclaw/bench/rules_lab/`, `openclaw/bench/rules_reference/` |
| `dashboard/` (operator progress UI) | `openclaw/dashboard/` |
| `reports/*.md`, templates | `openclaw/reports/` (drafts under `openclaw/reports/drafts/` where used) |
| `scripts/` (monitor, PDF build, etc.) | `openclaw/bench/scripts/`, `scripts/` (platform), as applicable—see `openclaw/references/testing_layers.md` |
| `1_e2e_frontend_selenium.py`, `2_sparql_*`, `3_long_term_*`, `4_hot_reload_test.py`, `automated_suite.py` | `openclaw/bench/e2e/` |
| `run_*.cmd` (Windows) | `openclaw/windows/` |
| `.github/workflows` (if any lab CI) | Prefer **open-fdd** `.github/workflows`; extend there, not the old repo |

**Not ported as-is:** ephemeral `reports/morning-review-*.md` / `overnight-summary-*.md` style files are **local lab journals**; recreate under `openclaw/reports/` or workspace `memory/` as needed. Do not expect historical files from the old repo to exist in git here.

---

## Roadmap buckets (for agents)

Use the same skill and docs as the product grows:

| Phase | Primary docs / assets |
|-------|------------------------|
| **Lab / regression** | `openclaw/references/testing_layers.md`, `openclaw/bench/e2e/`, `docs/operations/testing_plan.md` |
| **AI-assisted data modeling** | `docs/openclaw_integration.md`, `docs/modeling/llm_workflow.md`, `docs/modeling/ai_assisted_tagging.md`, `GET /data-model/export` → LLM → `PUT /data-model/import` |
| **Virtual / overnight operator** | `docs/operations/operator_framework.md`, `docs/operations/overnight_review.md`, `config/ai/operator_framework.yaml`, `docs/operations/openfdd_integrity_sweep.md` |
| **Future live HVAC / per-site clone** | `openclaw/references/future_operator_clones.md`, `docs/howto/cloning_and_porting.md` — site truth stays in the **live graph**, not in a forked doc repo |

---

## Why this file exists

OpenClaw and humans may still have links, clones, or muscle memory pointed at **open-fdd-automated-testing**. This reference is the **single redirect table** so bootstrap instructions stay correct without duplicating divergent copies of the same markdown.
