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
| `scripts/nf/` | `build_rule_catalog.py`, `build_sql_pack.py`, `gen_rule_docs.py`, `gen_cookbook.py`, `hooks/nf_app_sync.py` (deploy), `tools/` (read-only NF checks: LAN vs portal, history, BACnet wire validation) |
| `deploy/nf-caddy/` | Optional Caddy front door |
| `open_fdd/`, `tests/parity/` | PyPI pandas reference rules and the pandas == SQL parity tests |
| `tools/rdf-check/` | Turtle export checker |
| `tools/bacnet-scan/` | Read-only BACnet/IP site scanner (CSV + RDF); run it on a PC, never on the NF box |
| `docs/operations/nf/` | NF runbooks (internal, not published): Caddy front door, NF upgrade, Haystack tagging, BACnet validation, NF gotchas |
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
   what you changed; `docs/rules/*.md` is generated. See Docs style below.

## Docs style (published site)

The GitHub Pages site is five short sections, rules first. `scripts/check_pages.py` enforces this in CI.

| # | Section | Holds |
|---|---|---|
| 1 | **Rules** | SQL and pandas cookbooks, using SQL rules outside Open-FDD, parity and the parity harness, writing SQL rules |
| 2 | **Data model** | Haystack roles bind points to rule inputs; SI units; RDF and SPARQL |
| 3 | **Lite vs Full** | The two NF app editions, charts and export |
| 4 | **Normal Framework** | Short install and usage notes that link to the official NF docs; API reference |
| 5 | **Legacy** | One paragraph: earlier deployments are unsupported |

- **No new top-level pages without the owner's approval.** Put new material in an existing page, or in the repo
  (excluded from the site in `docs/_config.yml`). Internal material (prompts, plans, scratch notes, runbooks) never
  ships: keep it under `docs/prompts/`, `plans/`, `scratch/`, `operations/` or `migration/`.
- Short, plain, professional English. No recaps, no filler intros or closings, and do not repeat what another page
  says: link to it. Prefer tables and short examples. Aim for 300-800 words a page; the checker's budget is 800
  prose words (tables and code do not count). Rule cookbooks are generated, structured reference.
- Every rule entry states the SI unit of each input, threshold and numeric output. Units come from
  `sql/fdd/input_contract.json`, `open_fdd/data/units.json` and `sql/fdd/tuning_catalog.json` through
  `scripts/nf/docs_units.py`. Edit the generators (`gen_rule_docs.py`, `gen_cookbook.py`), never the generated pages.
- A page that moves or is removed leaves a "Page moved" stub; add it to `REDIRECTS` in `scripts/check_pages.py`
  and run `python3 scripts/check_pages.py --write-redirects`.
- No customer or company names, no stale version numbers, no dead links (`scripts/check_links.py`).

## Tests to run before a PR

```bash
node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs
(cd nf-app && npm ci && npm run typecheck)
python3 scripts/nf/build_rule_catalog.py --check && python3 scripts/nf/build_sql_pack.py --check
python3 scripts/nf/gen_rule_docs.py --check && python3 scripts/nf/gen_cookbook.py --check
python3 scripts/check_links.py && python3 scripts/check_pages.py
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
- Never edit generated files by hand (`fdd-catalog.json`, `rules/pack-*.json`, `docs/rules/index.md`, `docs/rules/sql-cookbook.md`, `docs/rules/pandas-cookbook.md`, `docs/rules/parity.md`).

## Live patching a box (last resort)

Prefer **halt-and-issue**: reproduce locally, fix on a `patch/5.0.x-...` branch, open a PR, and let the deploy agent push a release. Do not leave box-only edits that the next `install` / `push` will overwrite or that the hand-edit guard will block.

When a live hotfix is unavoidable (for example a StartHook type error that blocks verification after an otherwise good install):

1. **Capture first (read-only).** Download the installed file through the NF app file API (GET) or an equivalent read-only export into a local DIR **before** any write or restart. Do **not** rely on `nf_app_sync.py push --save-remote` for this step: that flag only saves copies when the hand-edit guard already found drift, and it may save nothing when the box still matches the last push. Never pass `--force` without the owner's explicit yes.
2. **Patch one file**, then commit. Write through the NF app file API (or a single-path push). For non-HTML files, commit the **identical bytes** on a patch branch immediately. For HTML, commit the repo source **without** generated `?v=` cache stamps; the deploy path may stamp for cache-busting. The box and the patch branch must not diverge on hook/logic content.
3. **Do not fake the push manifest.** Leave `static/version.json` `files` hashes alone for a box-only hotfix while `master` (or the revision you will deploy next) still lacks the fix. Expect `doctor` to list a hand edit until that revision is deployed and writes a truthful manifest. Refreshing hashes early hides drift and breaks the next upgrade.
4. **Restart, then verify.** Restart the NF app runtime (or otherwise reload hooks) after the file write so the next hook `run` loads the updated module. Then `doctor` and a targeted hook `run` (history/weather/fdd as relevant). Record CT timestamps; redact secrets.
5. **Port-back check** after the fix is on the deployed revision: download the installed app (read-only) and diff against that commit (strip cache stamps on HTML). Manifest sha mismatches of 0 and raw/strip equality on hooks mean parity is clean. `--save-remote` is appropriate here only when a push/install guard already reported drift.
6. **Document** the trap in `openfdd_agent_spec/skills/nf-gotchas.md` / `docs/operations/nf/nf-gotchas.md` in the same PR when it is a new NF console quirk.

Grok Bot (or the designated deploy agent) owns NF site deploys. Coding agents open the PR; they do not push to a live console unless the owner explicitly assigned that deploy.


## Security and reporting

See [SECURITY.md](SECURITY.md). CI runs ZAP against the mock NF, `npm audit` and gitleaks.
