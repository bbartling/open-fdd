# Open-FDD agent workspace — orientation

Plain Markdown on disk is the source of truth for **Cursor**, **Codex CLI**, and
similar agents. Product code lives in `services/`, `sql_rules/`, `frontend/`,
`mcp/`, `edge/`, `os/`. PyPI libraries live in `open_fdd/`. Orchestration lives in
**`openfdd_agent_spec/`**.

**Primary agent prompt (paste into new sessions):** [`../AGENTS.md`](../AGENTS.md)

**Software-engineering mission:** [`MILESTONE_A.md`](MILESTONE_A.md)

**Ops / edge soak prompts:** [`../docs/agent/`](../docs/agent/) — GHCR bench, nightly
retest. Do not confuse those with this engineering OS.

---

## Product vs libraries

| Layer | Owns |
| --- | --- |
| `services/` + `sql_rules/` + `frontend/web` | **Product:** central DataFusion SQL FDD + analytics, React SPA (`openfdd-web`), fieldbus, mqtt |
| `open_fdd/` | **PyPI libraries** for third-party tooling: ECM + pandas oracle (`rules` / `analytics` / `reporting`) — not the product runtime |
| `mcp/` | Optional read-first MCP → central |
| `edge/`, `os/` | Future concepts — **never delete** |
| `docs/rules/cookbook/` | Dual expression cookbooks (SQL + pandas) + parity matrix |
| `tools/open-fdd-vibe21-production/` | Active recovery + Vibe 21 twin program |
| `docs/migration/react-rust/capabilities.yaml` | Machine-readable capability ledger |
| `openfdd_agent_spec/` | Agent law, Milestone A, skills, session log |
| Playground vibe19/20 | External demos; consumers of PyPI |

**Naming (code truth):**

| Concept | Module / extra |
| --- | --- |
| Pandas oracle (PyPI) | `open_fdd.rules` (+ `open_fdd.analytics`) |
| Pip extras | `oracle`, `analytics`, `reporting` (`vibe19` deprecated alias through 4.3) |
| ECM math | `open_fdd.ecm_engineering` |
| Shared contracts | `open_fdd.contracts` — Phase 2 target (not shipped) |

---

## AI agent quick rules (read first)

1. Product FDD + Overview analytics = **DataFusion SQL** on GHCR. Never silent pandas fallback in central.
2. Pandas oracle stays forever on **PyPI** + cookbooks + vibe19 — never delete the pandas cookbook because production uses SQL.
3. Never delete the SQL cookbook because pandas remains the oracle.
4. **Product UI:** React SPA (`frontend/web` → `openfdd-web`, `compose.react.yml`) only. Overview = central `/api/analytics/*` (DataFusion) + client Plotly. Browser → central Rust `/api` only — **no Python in the product request path**.
5. **Internet-facing auth/UI hygiene:** Never put bench/dev secrets, credential file paths, default passwords, or JWT dumps on login or other product surfaces. Generic login errors only.
6. Test containers on **`OPENFDD_IMAGE_TAG=nightly`**, but **pin/run `sha-*`** per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).
7. Playground images: `ghcr.io/bbartling/vibe19:develop`, `vibe20:develop` (external).
8. `edge/` and `os/` are future concepts — never delete.
9. Bounded PRs only — see [`PR_PROTOCOL.md`](PR_PROTOCOL.md).
10. Prefer exact wheel install tests over editable-only validation for packaging PRs.
11. Never trust a moving GHCR tag alone — resolve/pull immutable `sha-*`, recreate containers, then record the digest.
12. Append [`SESSION_LOG.md`](SESSION_LOG.md) after non-trivial work.
13. Update [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) when Milestone A or product capability status changes.
14. CodeRabbit: fix actionable defects; reject suggestions that violate architecture.
15. vibe21 = separate plan — not Milestone A.
16. When blocked (secrets, permissions), finish non-blocked work and record the exact error.
17. Bound each PR to its declared scope.
18. **Active program:** [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/README.md) Master Loop. Keep [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml) honest.
19. For `frontend/web` work: follow [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md).
20. Central product image is **debian + Rust binaries only** — no Python. WattLab AFDD zip export is optional offline tooling (`OPENFDD_WATTLAB_PYTHON_EXPORT=1`).
21. **Site lock:** Overview + sidebar Active site are the only editors of `?site=`. `SectionTabs` (and sidebar App pages) must `navigate` with `hrefWithSession` so `site` + `eq` survive. FDD / RCx / Results / WattLab show a locked `zip:BUILDING_*` caption — no Building `<Select>`.
22. **FDD Plots = vibe19 `rule_result_chart`:** auto-load series; last y-axis title is `fault`; `confirmed_fault` is the last trace on the bottom domain (`domain[0] < 0.4`). A successful rule run with an empty overlay is a bug (fail the test), not a soft banner.
23. **RCx catalog freeze:** every `REQUIRED_RCX_PRESET_IDS` id must stay listed. Family picker order is `RCX_FAMILY_ORDER` (Zones first) plus empty Heat pump / Weather placeholders. Auto-run the selected preset when site+preset are set.
24. **Actions housekeeping:** default `GET /api/actions?limit=10`; `DELETE /api/actions/:id` and `DELETE /api/actions`; JSONL prune cap 50.
25. **Section radios:** left, horizontal, **after** hero + Equipment on Overview (never inside `.oracle-hero`, never centered in the logo column). Other pages: same left radio row at the top of the page body.
26. **Overview plot Expanders** default **open** — do not hide motor / mech / econ / BAS plot sections behind carets (`Expander` unmounts children when closed).
27. **FDD Plots series overlay** honors Lab/`session_config` `confirm_min` (and typed rule params); source may be `sql_detail_session`. After Update-this-rule, listen for `RULES_UPDATED` and refetch results + series.
28. **SCHED-1 portable occupancy:** numeric/boolean falsey (`0`, `0.0`, `false`) **and** string `unoccupied` (plus related tokens) — keep SQL (`sched1_unoccupied_runtime.sql`) and pandas `sched1` aligned.
29. **Low-RAM / bensbench:** never local stack `docker build`; prune old images before pull; wait for GHCR publish then pull `sha-*` / `nightly`. Synthetic-59 soaks use `scripts/synthetic_59_*.py`; B100 dump-parity stays paused; never edit goldens to hide misses.

---

## Authority order

1. Root [`AGENTS.md`](../AGENTS.md)
2. Machine manifests: [`ownership.yaml`](ownership.yaml), [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)
3. Current phase docs under [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/)
4. Generated OpenAPI / MCP / rule catalogs
5. Workflow guides and examples

Nested instructions may specialize but never contradict a higher authority.

## Bootstrap reading order

1. [`../AGENTS.md`](../AGENTS.md)
2. This file
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`ownership.yaml`](ownership.yaml)
4. [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md)
5. [`tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md`](../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md)
6. [`MILESTONE_A.md`](MILESTONE_A.md) if executing Milestone A
7. [`PR_PROTOCOL.md`](PR_PROTOCOL.md) before opening a PR
8. Matching skill
9. Cookbooks under `docs/rules/cookbook/`

---

## Skills

| Skill | Use when |
| --- | --- |
| [`openfdd-architecture`](skills/openfdd-architecture/SKILL.md) | Ownership / engine boundaries |
| [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md) | Product SPA (`frontend/web`) |
| [`openfdd-sql-fdd`](skills/openfdd-sql-fdd/SKILL.md) | DataFusion SQL rules |
| [`openfdd-pypi-oracle`](skills/openfdd-pypi-oracle/SKILL.md) | PyPI pandas oracle packaging |
| [`openfdd-cookbook-parity`](skills/openfdd-cookbook-parity/SKILL.md) | Dual cookbook honesty |
| [`openfdd-stack-ghcr`](skills/openfdd-stack-ghcr/SKILL.md) | GHCR pull / recreate |
| [`openfdd-ecm-engineering`](skills/openfdd-ecm-engineering/SKILL.md) | ECM math library |
| [`openfdd-milestone-a-pr`](skills/openfdd-milestone-a-pr/SKILL.md) | Milestone A PR loop |
