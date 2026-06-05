---
title: Docs cleanup plan (internal)
nav_exclude: true
---

# Docs cleanup plan

Internal inventory for the 2026 docs overhaul on branch `docs/security-refresh`. Not linked in public nav.

## Goals

- Cut public docs ~50% by merging duplicates and demoting integrator/deep dives to the appendix.
- Remove lab-specific naming (Acme, bensserver) from primary pages; use *demo site*, *edge host*, *control machine*.
- Minimize AI-agent workflow in human docs; defer to `AGENTS.md`.
- GHCR-first quick start; local build in Developer Guide.

## Page disposition

| Action | Paths |
|--------|--------|
| **Replace** | `index.md`, new `quick-start/*`, `developer/*`, `architecture/*`, `operator-bridge/*`, `bacnet/*`, `rule-cookbook/*`, `fault-codes/*`, `security/*` |
| **Keep (appendix)** | `appendix/bridge_api.md`, `appendix/python-package.md`, `appendix/configuration.md`, `appendix/glossary.md` |
| **Delete** | `getting_started.md`, `overview.md`, `edge_deploy.md`, `edge_deploy_docker.md`, `howto/*`, `concepts/*`, `operations/*`, `expression_rule_cookbook*.md`, `modular_architecture.md`, `operational_analytics.md`, `local_ollama.md`, `column_map_resolvers.md`, `modeling/*`, `rules/*`, `api/*`, `howto/docker_image_upgrade.md`, `open_fdd_playground_pypi.md`, `standalone_csv_pandas.md`, `bacnet-rdf-and-brick.md`, `configuration.md`, `examples.md`, `security.md`, `contributing.md`, `architecture/adr-001*.md`, `architecture/arrow_data_plane.md`, `architecture/edge_stack.md` |
| **Moved to AGENTS.md** | AI bootstrap checklist, skill routing tables, Acme secrets paths |

## New nav (Just the Docs)

1. Home — `index.md`
2. Quick Start — `quick-start/`
3. Developer Guide — `developer/`
4. Architecture — `architecture/`
5. Operator Bridge — `operator-bridge/`
6. BACnet — `bacnet/`
7. Rule Cookbook — `rule-cookbook/`
8. Fault Codes — `fault-codes/`
9. Security — `security/`
10. Appendix — `appendix/`

## Validation

```bash
cd docs && bundle install && bundle exec jekyll build
rg -i 'acme|bensserver|coming soon|AI-assisted bootstrap' docs --glob '*.md' | grep -v docs_cleanup_plan
```
