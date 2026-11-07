# Agent guide: Open-FDD 5.0

Open-FDD is a **Normal Framework (NF) app**: fault detection and diagnostics (FDD) and retro-commissioning
(RCx) for HVAC, running inside NF on the building's edge box. The Rust central stack (4.x) is gone; it is frozen
at tag `v4.0.11-central`. Read [README.md](README.md), [nf-app/README.md](nf-app/README.md) and
[docs/architecture/adr-014-open-fdd-as-nf-plugin.md](docs/architecture/adr-014-open-fdd-as-nf-plugin.md) first.

The agent spec lives in [`openfdd_agent_spec/`](openfdd_agent_spec/README.md): architecture, data contract and
task skills (add a chart, add a rule, model a site, deploy, security checks, TypeScript, BACnet validation, NF gotchas). Claude Code and Cursor
find the skills through thin pointers in `.claude/skills/` and `.agents/skills/`.

## Layout

| Path | What |
|---|---|
| `nf-app/` | The full app: `app.json`, `static/` UI, `hooks/` (`fdd`, `weather`, `sparql`), `rules/` (SQL packs), `rcx-parity.json`, `dev/mock-nf.mjs`, `tests/` |
| `lite/` | Open-FDD Lite: the no-FDD edition for 1 GB boxes (Raspberry Pi) |
| `sql/fdd/` | The FDD math (77 Postgres rules, registry, role map). Packs in `nf-app/rules/` are generated from it |
| `scripts/nf/` | `build_rule_catalog.py`, `build_sql_pack.py`, `gen_rule_docs.py`, `hooks/nf_app_sync.py` (deploy), `tools/` (read-only NF checks: LAN vs portal, history, BACnet wire validation) |
| `deploy/nf-caddy/` | Optional Caddy front door |
| `open_fdd/`, `tests/parity/` | PyPI pandas reference rules and the pandas == SQL parity tests |
| `tools/rdf-check/` | Turtle export checker |
| `tools/bacnet-scan/` | Read-only BACnet/IP site scanner (CSV + RDF); run it on a PC, never on the NF box |
| `docs/operations/nf/` | NF runbooks: Lite or full, Caddy front door, NF upgrade, Haystack tagging, BACnet validation, NF gotchas |
| `docs/` | GitHub Pages site (Jekyll, Just the Docs) |

## Rules

1. **SI math only.** FDD and analytics run in SI; convert on ingest and for display with `static/units.js`
   (`ofddUnits`). Never convert inside a rule or a threshold.
2. **No site-specific code.** No site names, equipment names, point names, uuids or IPs in code. Everything is
   discovered from NF's Haystack model (NF classes first, then markers). To support a site, tag it in NF.
3. **Faults are the bottom lane.** Show faults only with `rcxWithFaultLane(option, lanes)` (`static/rcx.js`):
   a 0/1 lane at the bottom of the plot. New charts register with `rcxView({...})` and an entry in
   `nf-app/rcx-parity.json`.
4. **Strict CSP, one honest exception.** No inline scripts or styles; every library is vendored and pinned (never a
   release younger than two weeks) and served from the app itself. The single exception is the Normal Online
   (portal) login: when NF reports Clerk, `static/nf.js` loads `clerk-js` at an **exact pinned version**
   (`CLERK_JS_VERSION`) from the Clerk host named in the portal's publishable key. Because that host is only known
   at runtime, the page CSP keeps `script-src 'self' https:` (and `connect-src 'self' https:`). Do not describe the
   app as "self-only" or "no CDN at runtime", and do not add any other remote script. Bump the Clerk pin only to a
   release at least two weeks old, in both `nf-app/static/nf.js` and `lite/static/nf.js`.
5. **One FDD math.** Change rules in `sql/fdd`, then rebuild the catalog and packs; the SQLite pack must match Postgres.
6. **Small PR slices** (one concern each, easy for a small model to review). Update the docs page that describes
   what you changed; `docs/fdd-rules.md` is generated.

## Tests to run before a PR

```bash
node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs
(cd nf-app && npm ci && npm run typecheck)
python3 scripts/nf/build_rule_catalog.py --check && python3 scripts/nf/build_sql_pack.py --check
python3 scripts/nf/gen_rule_docs.py --check
python3 scripts/check_links.py
```

Local development needs no NF box: `node nf-app/dev/mock-nf.mjs`, then open
`http://127.0.0.1:8765/api/v1/apps/static/open-fdd/`.

## Deploy

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push nf-app/app.json     # full
python3 scripts/nf/hooks/nf_app_sync.py --env ~/.secrets/nf_console.env push lite/app.json       # Lite
```

The env file (`NF_CONSOLE_URL`, `CONSOLE_USERNAME`, `CONSOLE_PASSWORD`) lives outside git. The alternative is the
NF MCP server (`manage_app`, `deploy_hook`); see [docs/install.md](docs/install.md). Static files are cached for 5
minutes, so reload with `?v=N` after a deploy.

## Never

- Never deploy heavy things to a Pi or other small box: build, test and run engines on a PC; the Pi runs Lite only.
- Never write BACnet (or any protocol) to field devices without the owner's explicit approval. The app writes only
  its own result points and weather variables.
- Never commit secrets: NF passwords, API keys, tokens, `auth.caddy`, certificates, private hostnames.
- Never pass an existing point uuid to `POST /api/v1/bacnet/local` (it overwrites that point).
- Never reintroduce Rust, GHCR images, a second historian or a second auth system; NF owns those.
- Never edit generated files by hand (`fdd-catalog.json`, `rules/pack-*.json`, `docs/fdd-rules.md`).

## Security and reporting

See [SECURITY.md](SECURITY.md). CI runs ZAP against the mock NF, `npm audit` and gitleaks.
