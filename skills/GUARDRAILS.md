# Skill guardrails

Canonical skill tree: `skills/<topic>/SKILL.md` with optional `references/`, `scripts/`, and `assets/`.

## Rules

- Do not paste full operator manifests or secrets into skills or memory files.
- Extend an existing topic folder before creating a new one unless `BUILD_CHECKPOINTS` or the operator explicitly requests a new domain.
- At most one material skill-folder change per critique wake unless maintenance is explicit.
- After adding a skill folder, cross-link from `AGENTS.md` when routing changes.
- Keep `SKILL.md` under ~500 lines; move tables to `references/REFERENCE.md`.
- Promote stable working patterns from `workspace/memory/architecture/working-divergence.md` into `references/`, not into long SKILL bodies.
