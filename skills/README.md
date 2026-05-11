# Open-FDD skills

Domain skills teach Codex (or other agents) how to **build** operator-specific stacks on top of the `open-fdd` engine. Each folder is one domain.

## Layout

```text
skills/<domain-skill>/
  SKILL.md                 # required — when to use, quick start, patterns, verification
  references/
    REFERENCE.md           # optional — API tables, env vars, legacy source maps
  scripts/                 # optional — small repeatable helpers only
```

## Authoring rules

- YAML frontmatter: `name` (folder slug) and `description` (third-person WHAT + WHEN triggers).
- Keep `SKILL.md` under ~500 lines; move tables to `references/REFERENCE.md`.
- Link to [docs/expression_rule_cookbook.md](../docs/expression_rule_cookbook.md) for rule authoring; do not fork cookbook prose here.
- Cite retired monolith paths in `REFERENCE.md` when distilling legacy behavior.
- Cross-link sibling skills with relative paths to `SKILL.md`.

## Catalog

See [AGENTS.md](../AGENTS.md) for the routing table.
