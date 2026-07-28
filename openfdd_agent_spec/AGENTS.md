# Open-FDD agent workspace — orientation

Plain Markdown on disk is the source of truth for **Cursor**, **Codex CLI**, and
similar agents. Product code lives in `open_fdd/`, `services/`, `sql_rules/`,
`mcp/`, `edge/`, `os/`. Orchestration lives in **`openfdd_agent_spec/`**.

**Primary agent prompt (paste into new sessions):** [`../AGENTS.md`](../AGENTS.md)

**Software-engineering mission:** [`MILESTONE_A.md`](MILESTONE_A.md)

**Ops / edge soak prompts (separate):** [`../docs/agent/`](../docs/agent/) — GHCR
bench, nightly retest, WSL sleep. Do not confuse those with this engineering OS.

---

## Product vs orchestration

| Layer | Owns |
| --- | --- |
| `open_fdd/` | PyPI libraries: ECM + pandas oracle (`rules` / `analytics` / `reporting`) |
| `services/` + `sql_rules/` | Production stack: central DataFusion SQL FDD, Streamlit UI, fieldbus, mqtt |
| `mcp/` | Optional read-first MCP → central |
| `edge/`, `os/` | Future concepts — **never delete** |
| `docs/rules/cookbook/` | Dual expression cookbooks (SQL + pandas) + parity matrix |
| `openfdd_agent_spec/` | Agent law, Milestone A, skills, session log |
| Playground vibe19/20 | Educational/demo apps; consumers of PyPI; interim GHCR |

**Repos naming (code truth):**

| Concept | Module / extra |
| --- | --- |
| Pandas oracle | `open_fdd.rules` (+ `open_fdd.analytics`) |
| Pip extras | `oracle`, `reporting`, `vibe19` |
| ECM math | `open_fdd.ecm_engineering` |
| Shared contracts | `open_fdd.contracts` — **Phase 2 target (not shipped)** |

Do **not** rename `open_fdd.rules` → `open_fdd.oracle` without an explicit product decision.

---

## AI agent quick rules (read first)

1. Production FDD = **DataFusion SQL** on GHCR (`sql_rules/`). Never silent pandas fallback in central.
2. Pandas oracle stays forever — cookbooks + vibe19 + PyPI `rules`/`analytics`. Never delete the pandas cookbook because production uses SQL.
3. Never delete the SQL cookbook because pandas remains the oracle.
4. One Streamlit product UI: `services/ui` → `openfdd-ui`. Not a Vite/Caddy SPA.
5. Test open-fdd containers on **`OPENFDD_IMAGE_TAG=nightly`** (master retargets `:nightly`).
6. Playground images: `ghcr.io/bbartling/vibe19:develop`, `vibe20:develop`.
7. `edge/` and `os/` are future concepts — never delete.
8. Bounded PRs only — see [`PR_PROTOCOL.md`](PR_PROTOCOL.md).
9. Migration pattern: inventory → characterization → shared impl → parity → cutover → **delete twin** → regression → docs.
10. Do not copy code into Open-FDD and leave both implementations active.
11. Vibe 19 may keep Streamlit UX, custom `CUSTOM-*` rules, demos — not canonical rule/analytics twins.
12. Vibe 20 owns EnergyPlus — keep IDF/sim/orchestration; delete only **generic** ECM twins after parity.
13. Prefer exact wheel install tests over editable-only validation for packaging PRs.
14. Never trust a moving GHCR tag alone — resolve/pull immutable `sha-*`, recreate containers, then record the digest.
15. Append [`SESSION_LOG.md`](SESSION_LOG.md) after non-trivial work.
16. Update [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) whenever Milestone A status changes (not only after merge).
17. CodeRabbit: fix actionable defects; reject suggestions that violate architecture.
18. Do not retire playground GHCR without an open-fdd capability parity matrix.
19. vibe21 = separate plan — not Milestone A.
20. When blocked (secrets, permissions, private data), finish non-blocked work and record the exact error.
21. Bound each PR to its declared scope — docs-only PRs do not require cross-repo pin bumps or GHCR refreshes.

---

## Bootstrap reading order

1. [`../AGENTS.md`](../AGENTS.md) — stack + MCP safety
2. This file
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`ownership.yaml`](ownership.yaml)
4. [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) — what is already done
5. [`MILESTONE_A.md`](MILESTONE_A.md) — full mission if executing Milestone A
6. [`PR_PROTOCOL.md`](PR_PROTOCOL.md) before opening a PR
7. Skill matching the work (below)
8. Code truth: `docs/migration/`, `docs/rules/cookbook/`, `docs/architecture/`

---

## Local repositories

Default checkouts on Ben’s WSL (adjust if your clone paths differ):

```text
~/open-fdd                          # bbartling/open-fdd  (default: master)
~/py-bacnet-stacks-playground       # bbartling/py-bacnet-stacks-playground (default: develop)
  vibe_code_apps_19/
  vibe_code_apps_20/
```

Sibling-repo locations are **examples** — resolve via `git rev-parse --show-toplevel` / env, not hardcoded usernames.
---

## Skill index

| Skill | Use when |
| --- | --- |
| [`openfdd-architecture`](skills/openfdd-architecture/SKILL.md) | Ownership, forbidden imports, dual cookbooks |
| [`openfdd-pypi-oracle`](skills/openfdd-pypi-oracle/SKILL.md) | `open_fdd.rules` / analytics / reporting / extras |
| [`openfdd-ecm-engineering`](skills/openfdd-ecm-engineering/SKILL.md) | ECM calculators, vibe20 twin deletion |
| [`openfdd-sql-fdd`](skills/openfdd-sql-fdd/SKILL.md) | DataFusion registry, `sql_rules/`, no pandas in central |
| [`openfdd-cookbook-parity`](skills/openfdd-cookbook-parity/SKILL.md) | Cookbook CI, parity matrix, docs headings |
| [`openfdd-stack-ghcr`](skills/openfdd-stack-ghcr/SKILL.md) | Nightly stack pull, labels, smoke |
| [`openfdd-milestone-a-pr`](skills/openfdd-milestone-a-pr/SKILL.md) | Inventory → parity → cutover → delete loop |

---

## Repo map (engineering)

| Path | Role |
| --- | --- |
| `open_fdd/ecm_engineering/` | Default-install ECM math + CLI |
| `open_fdd/rules/` | Pandas cookbook oracle |
| `open_fdd/analytics/` | Oracle analytics helpers |
| `open_fdd/reporting/` | Findings / DOCX / xlsx reporting |
| `sql_rules/` | Production SQL registry + rule files |
| `services/ui/` | Product Streamlit (SQL FDD + WattLab export) |
| `services/central/` | Rust API + DataFusion |
| `docs/rules/cookbook/` | Human-readable SQL + pandas cookbooks |
| `docs/migration/` | Historical audit + matrices |
| `.github/workflows/` | See [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md) |
