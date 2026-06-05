---
title: Documentation checklist (internal)
nav_exclude: true
---

# Documentation quality checklist

Run before merging docs PRs:

- [ ] `cd docs && bundle exec jekyll build` succeeds
- [ ] No broken `parent:` titles (must match parent page `title` exactly)
- [ ] `rg -i 'acme|bensserver' docs --glob '*.md' | grep -v docs_cleanup_plan | grep -v DOCUMENTATION_CHECKLIST` is empty
- [ ] GHCR commands use real image names (`ghcr.io/bbartling/openfdd-*`)
- [ ] BACnet write warnings present in Quick Start and BACnet sections
- [ ] README.md unchanged unless explicitly requested (docs branch policy)
