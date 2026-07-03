---
title: Documentation site
parent: Operations
nav_order: 4
---

# GitHub Pages documentation

Published docs: [https://bbartling.github.io/open-fdd/](https://bbartling.github.io/open-fdd/)

Open-FDD documentation is built with [Jekyll](https://jekyllrb.com/) and the [Just the Docs](https://just-the-docs.com/) theme. Deployment uses **GitHub Actions only** — not the legacy GitHub Pages Jekyll builder.

## How it works

| Item | Value |
|------|--------|
| Workflow | [`.github/workflows/docs-pages.yml`](https://github.com/bbartling/open-fdd/blob/master/.github/workflows/docs-pages.yml) |
| Source | `docs/` on `master` |
| Theme | `just-the-docs` via Bundler (`docs/Gemfile`) |
| Pages source | **GitHub Actions** (Settings → Pages) |

On each push that touches `docs/**` or the workflow file, CI runs `bundle exec jekyll build` and publishes the `_site` artifact with `deploy-pages`.

## Local preview

Requires Ruby 3.2+ and Bundler:

```bash
cd docs
bundle install
bundle exec jekyll serve --livereload --baseurl ""
```

Open [http://127.0.0.1:4000](http://127.0.0.1:4000). For production URL paths, use `--baseurl /open-fdd` instead of an empty baseurl.

## Editing guidelines

- **Published pages** live at the top level of `docs/` (Quick Start, Architecture, Drivers, etc.).
- **Archive** (`docs/archive/`) is excluded from the site build — historical bench notes and Python-era references only.
- Use Just the Docs front matter: `title`, `nav_order`, `parent`, `has_children` as needed.
- Prefer `{{ site.baseurl }}` for internal links so Pages paths resolve correctly.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Red **pages build and deployment** (legacy) workflow | Ensure repo **Settings → Pages → Build and deployment → Source** is **GitHub Actions**, not “Deploy from a branch”. |
| `just-the-docs theme could not be found` on legacy build | Expected when legacy source is enabled; switch to GitHub Actions or use this workflow. |
| Docs workflow fails on `bundle` | Run `bundle lock` in `docs/` and commit `Gemfile.lock`. |
| 404 after reorganization | Use search or the [home page]({{ site.baseurl }}/); see `docs/404.md`. |
