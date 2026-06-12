---
title: Contributing
parent: Developer Guide
nav_order: 4
---

# Contributing

## Expectations

- Open an issue or discuss large changes before big refactors.
- Keep PRs focused; include test or docs updates when behavior changes.
- Do not commit secrets (`auth.env.local`, Ansible `secrets/*.env.local`, commissioning CSVs with real site data).
- Follow existing code style in `workspace/api/` and `workspace/dashboard/`.

## Pull request checklist

- [ ] Tests pass locally (`./scripts/build_and_test.sh` or scoped pytest)
- [ ] Docs updated if user-facing behavior changed
- [ ] `docs/` Jekyll build succeeds
- [ ] No credentials in diff
- [ ] Auth/Caddy/header changes: re-run [pentest verify + LAN ZAP]({{ "/developer/security-testing/" | relative_url }}) and update [ZAP baseline]({{ "/security/zap-baseline/" | relative_url }}) if expectations changed

## Repository layout (short)

| Path | Contents |
|------|----------|
| `workspace/api/` | Operator Bridge (FastAPI) |
| `workspace/dashboard/` | React SPA |
| `open_fdd/` | PyPI package (`arrow_runtime`, `playground`) |
| `docker/` | Compose files and image contexts |
| `infra/ansible/` | Edge deploy playbooks |
| `docs/` | This site (Jekyll + Just the Docs) |

## Docs links (GitHub Pages)

The site is a **project page** at `https://bbartling.github.io/open-fdd/` (`baseurl: /open-fdd` in `docs/_config.yml`).

- **Do not** use Jekyll `{% link path.md %}` in Markdown body text — it omits `baseurl` and 404s on GitHub Pages.
- **Do** use `[label]({{ "/section/page/" | relative_url }})` for internal links.
- After `bundle exec jekyll build`, run `python3 scripts/check_docs_internal_links.py --site _site` from the repo root.

## Security issues

Do not file public issues for vulnerabilities. Contact the maintainer or use GitHub private security advisories.

## Agent-assisted development

Cursor/Claude contributors: read `AGENTS.md` and `skills/` for automation boundaries. Public docs intentionally avoid agent playbook detail.
