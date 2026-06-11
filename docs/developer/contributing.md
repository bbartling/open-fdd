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
- [ ] Auth/Caddy/header changes: re-run [pentest verify + LAN ZAP]({% link developer/security-testing.md %}) and update [ZAP baseline]({% link security/zap-baseline.md %}) if expectations changed

## Repository layout (short)

| Path | Contents |
|------|----------|
| `workspace/api/` | Operator Bridge (FastAPI) |
| `workspace/dashboard/` | React SPA |
| `open_fdd/` | PyPI package (`arrow_runtime`, `playground`) |
| `docker/` | Compose files and image contexts |
| `infra/ansible/` | Edge deploy playbooks |
| `docs/` | This site (Jekyll + Just the Docs) |

## Security issues

Do not file public issues for vulnerabilities. Contact the maintainer or use GitHub private security advisories.

## Agent-assisted development

Cursor/Claude contributors: read `AGENTS.md` and `skills/` for automation boundaries. Public docs intentionally avoid agent playbook detail.
