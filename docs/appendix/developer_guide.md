---
title: Developer guide
parent: Appendix
nav_order: 2
nav_exclude: true
---

# Developer guide

For contributors working on the **`open_fdd`** package.

---

## Local workflow

1. Create a virtual environment and install in editable mode with dev tools:

   ```bash
   pip install -e ".[dev]"
   pre-commit install   # optional, if you use the repo’s hooks
   ```

2. Run the test suite:

   ```bash
   pytest
   ```

3. Format with **Black** (version and line length are pinned in `pyproject.toml`).

---

## Code layout

- **`open_fdd/engine/`** — `RuleRunner`, rule loading, checks (bounds, flatline, expression, …), `ColumnMapResolver` and manifest helpers.
- **`open_fdd/schema/`** — pydantic models for fault results and related structures.
- **`open_fdd/reports/`** — optional reporting helpers; may require extra packages in your environment.

Public imports are re-exported from **`open_fdd`** and **`open_fdd.engine`** where documented on [Engine API](../api/engine).

---

## Adding or changing rules

- YAML rule files live alongside your application or under **`examples/`** / **`open_fdd/tests/fixtures/rules/`** for tests.
- Extend engine behavior via the documented check types and expression language; see [Rules overview](../rules/overview) and [Expression rule cookbook](../expression_rule_cookbook).

---

## Documentation site

The public site at [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/) is built from **`docs/`** with **Jekyll** and the **[Just the Docs](https://just-the-docs.github.io/just-the-docs/)** theme (sidebar nav, search, syntax highlighting). Custom typography and tables live in **`docs/_includes/head_custom.html`**.

CI job **`docs`** (and workflow **`Docs (GitHub Pages)`** on push to `master` / `main`) run `bundle exec jekyll build` plus HTMLProofer on the built site. After substantive edits, preview locally from `docs/`:

```bash
cd docs
bundle install
bundle exec jekyll serve
```

The theme is installed via the **`just-the-docs`** gem in `docs/Gemfile` (no `jekyll-remote-theme` / GitHub API fetch required). Open http://127.0.0.1:4000/open-fdd/ to preview with the correct `baseurl`.
