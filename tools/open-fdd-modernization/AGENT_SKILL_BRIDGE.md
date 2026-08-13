# Agent skill bridge — Phase 1 React/Rust

Agents executing Open-FDD Phase 1 must treat **both** trees as law:

| Tree | Role |
| --- | --- |
| [`openfdd_agent_spec/`](../../openfdd_agent_spec/) | Product/engineering OS: ownership, Milestone A/B/C skills, PR protocol, checkpoints |
| [`tools/open-fdd-modernization/`](./) | React/Rust Phase 1–3 program: milestones, prompts, parity tests |
| [`docs/migration/react-rust/`](../../docs/migration/react-rust/) | Durable ledgers updated in every Phase 1 PR |

They are complementary, not alternatives. Milestone A skills still apply when a
Phase 1 PR touches SQL FDD, cookbooks, GHCR, ECM, or packaging.

## Required read order (new session)

1. Root [`AGENTS.md`](../../AGENTS.md)
2. [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md)
3. [`openfdd_agent_spec/PR_PROTOCOL.md`](../../openfdd_agent_spec/PR_PROTOCOL.md) (bounded PRs)
4. [`AGENTS.md`](AGENTS.md) (this kit — Open-FDD React product UI)
5. This bridge
6. [`openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`](../../openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md) **before any UI work**
7. [`AGENT_EXECUTION_SYSTEM.md`](AGENT_EXECUTION_SYSTEM.md)
8. Phase doc + ledgers for the selected `P1-M?-??`

## Skill router

| Work | Skill |
| --- | --- |
| React SPA pages, shell, widgets, product UI | [`openfdd-react-spa`](../../openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md) |
| Ownership / forbidden imports | [`openfdd-architecture`](../../openfdd_agent_spec/skills/openfdd-architecture/SKILL.md) |
| DataFusion / `sql_rules/` / no pandas in central | [`openfdd-sql-fdd`](../../openfdd_agent_spec/skills/openfdd-sql-fdd/SKILL.md) |
| Pandas oracle / PyPI extras | [`openfdd-pypi-oracle`](../../openfdd_agent_spec/skills/openfdd-pypi-oracle/SKILL.md) |
| Cookbook dual expression / parity CI | [`openfdd-cookbook-parity`](../../openfdd_agent_spec/skills/openfdd-cookbook-parity/SKILL.md) |
| ECM calculators | [`openfdd-ecm-engineering`](../../openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md) |
| Nightly GHCR stack | [`openfdd-stack-ghcr`](../../openfdd_agent_spec/skills/openfdd-stack-ghcr/SKILL.md) |
| Inventory→parity→cutover→delete twin | [`openfdd-milestone-a-pr`](../../openfdd_agent_spec/skills/openfdd-milestone-a-pr/SKILL.md) |
| Phase 1 loop prompts | [`prompts/PHASE_1_LOOP_PROMPTS.md`](prompts/PHASE_1_LOOP_PROMPTS.md) |

## Open-FDD override for generic FastAPI text

Some generic modernization docs mention FastAPI as one possible backend.
For this repository:

- **Backend = `services/central` (Rust).**
- **Compute = DataFusion / `sql_rules/`.**
- **Do not introduce FastAPI or any Python browser API.**
- Python remains oracle-only until a separate Phase 2 deletion decision.

## Checkpoint / session hygiene

When Phase 1 milestone status changes, update **both**:

- [`docs/migration/react-rust/SESSION_LOG.md`](../../docs/migration/react-rust/SESSION_LOG.md)
- [`openfdd_agent_spec/BUILD_CHECKPOINTS.md`](../../openfdd_agent_spec/BUILD_CHECKPOINTS.md) (React/Rust section)
- [`openfdd_agent_spec/SESSION_LOG.md`](../../openfdd_agent_spec/SESSION_LOG.md) for non-trivial agent sessions

## Cursor rule

Project rule: [`.cursor/rules/openfdd-phase1-react-parity.mdc`](../../.cursor/rules/openfdd-phase1-react-parity.mdc)
auto-applies when editing React, migration ledgers, or this kit.
