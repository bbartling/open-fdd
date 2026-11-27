# Agent guide: Open-FDD 5.0

Open-FDD is a **Normal Framework (NF) app**: fault detection and diagnostics (FDD) and retro-commissioning
(RCx) for HVAC, running inside NF on the building's edge box. The Rust central stack (4.x) is gone; it is frozen
at tag `v4.0.11-central`. Read [README.md](README.md), [nf-app/README.md](nf-app/README.md) and
[docs/architecture/adr-014-open-fdd-as-nf-plugin.md](docs/architecture/adr-014-open-fdd-as-nf-plugin.md) first.

The agent spec directory is [`openfdd_agent_spec/`](openfdd_agent_spec/README.md): architecture, data contract and
task skills. Claude Code and Cursor load the skills through the pointers in `.claude/skills/` and `.agents/skills/`.
There is no `CLAUDE.md` and no `.cursor` rules file. `scripts/check_agent_spec.py` checks the paths, commands and
rule ids those files name.

## Layout

| Path | What |
|---|---|
| `nf-app/` | The full app: `app.json`, `static/` UI, `hooks/` (`fdd`, `weather`, `sparql`), `rules/` (SQL packs), `rcx-parity.json`, `dev/mock-nf.mjs`, `tests/` |
| `lite/` | Open-FDD Lite: the no-FDD edition for 1 GB boxes (Raspberry Pi) |
| `sql/fdd/` | The FDD math (83 SQL rules in `nf-app/static/fdd-catalog.json`, registry, role map). Packs in `nf-app/rules/` are generated from it. The NF app runs that SQL on Node DuckDB (`@duckdb/node-api` `2.0.1-r.1`) and Timescale. pandas must match SQL except `open_fdd/data/parity_known_differences.json`. `duckdb>=2.0.1` is the Python test extra |
| `sql/analytics/` | Read-only analytics SQL. Pandas twins: `open_fdd/analytics/sql_*.py` |
| `roles/` | Point-role contract `roles/openfdd-roles.json` (`1.1.0-draft.1`). 223P names are the core; Haystack is the binding overlay. QUDT local names (`DEG_C`, `PA`, …) are the wire units |
| `openapi/`, `contract/` | UI API contract `openapi/open-fdd-ui-api.yaml` (`1.0.0`) and the Node 22 mock |
| `scripts/nf/` | `scripts/nf/build_rule_catalog.py`, `scripts/nf/build_sql_pack.py`, `scripts/nf/gen_rule_docs.py`, `scripts/nf/gen_cookbook.py`, `scripts/nf/build_app_dist.py`, `scripts/nf/hooks/nf_app_sync.py` (deploy), `scripts/nf/tools/` (read-only NF checks: LAN vs portal, history, BACnet wire validation) |
| `deploy/nf-caddy/` | Optional Caddy front door |
| `open_fdd/`, `tests/parity/` | PyPI pandas reference rules and the pandas == SQL parity tests |
| `open_fdd/ml/`, `sql/analytics/` | PyPI ML FDD tools (`open-fdd-ml`, LBNL benchmark) and portable SQL analytics (z-score) |
| `open_fdd/ontology_audit/` | PyPI ontology coverage audit and RDF model doctor (`open-fdd-ontology-audit`, #1569), offline, read-only |
| `tools/rdf-check/` | Turtle export checker |
| `tools/bacnet-scan/` | Read-only BACnet/IP site scanner (CSV + RDF); run it on a PC, never on the NF box |
| `docs/operations/nf/` | NF runbooks (internal, not published): Caddy front door, NF upgrade, Haystack tagging, BACnet validation, NF gotchas |
| `docs/` | GitHub Pages site (Jekyll, Just the Docs) |

## Rules

1. **SI math only.** FDD and analytics run in SI. Thresholds are SI and the unit is shown. Imperial is display-only,
   through `nf-app/static/units.js` (`ofddUnits`). Never convert inside a rule or a threshold. Roles whose
   `sql/fdd/input_contract.json` scale is `fraction` are already 0–1 in the scratch tables.
2. **223P roles, Haystack overlay.** Role names come from `roles/openfdd-roles.json` (`1.1.0-draft.1`). Haystack
   markers and NF classes only bind a point to that role. The SQL catalog still uses legacy keys (`legacy_keys` in
   the roles file). To support a site, tag it in NF. No site names, equipment names, point names, uuids or IPs in code.
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
5. **One FDD math.** Change rules in `sql/fdd`, then rebuild the catalog and packs (83 SQL rules). The NF app runs two engines:
   Node DuckDB (`@duckdb/node-api` 2.0.1-r.1) for a single site, and Timescale for Full. `auto` picks DuckDB unless
   Timescale is configured. A saved option named `sqlite` or `pglite` fails and names `duckdb`. Parity compares pandas
   with Node DuckDB and, when a server is configured, Timescale. If `@duckdb/node-api` does not load, the DuckDB build
   stops and does not switch engines. The badge in the plugin header is `DuckDB build` or `Timescale build`. Sensor
   sweeps (`SV-RANGE`, `SV-SPIKE`, `SV-FLATLINE`, `SV-STALE`, `SV-RATE`) return one row per sensor.
6. **Small PR slices** (one concern each, easy for a small model to review). Update the docs page that describes
   what you changed; `docs/rules/*.md` is generated. See Docs style below.

## Docs style (published site)

The GitHub Pages site is five short sections, rules first. `scripts/check_pages.py` enforces this in CI.

| # | Section | Holds |
|---|---|---|
| 1 | **Rules** | SQL and pandas cookbooks, using SQL rules outside Open-FDD, parity and the parity harness, [testing and parity](docs/testing-parity.md), writing SQL rules |
| 2 | **Data model** | Haystack roles bind points to rule inputs; SI units; RDF and SPARQL |
| 3 | **Lite vs Full** | The two NF app editions, charts and export |
| 4 | **Normal Framework** | Short install and usage notes that link to the official NF docs; API reference |
| 5 | **Legacy** | One paragraph: earlier deployments are unsupported |

- **No new top-level pages without the owner's approval.** Put new material in an existing page, or in the repo
  (excluded from the site in `docs/_config.yml`). Internal material never ships. Runbooks stay in
  `docs/operations/`. Migration notes stay in `docs/migration/`. `scripts/check_pages.py` also excludes the
  names prompts, plans and scratch.
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

CI and the hook typecheck use Node 22. Do not move the app to another major.

FDD parity is SQL == pandas == the SPARQL client (`parity.yml`, nightly `parity-stress.yml`). RDF parity is rdflib against `nf-app/hooks/sparql.js` (`rdf-parity.yml`). OntoEnv and Shifty run in Python CI (`ontology-223p.yml`); the plugin does not resolve `owl:imports` or run SHACL. Pins and schedules: [docs/testing-parity.md](docs/testing-parity.md).

```bash
node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs
(cd nf-app && npm ci && npm run typecheck)
python3 scripts/nf/build_rule_catalog.py --check && python3 scripts/nf/build_sql_pack.py --check
python3 scripts/nf/gen_rule_docs.py --check && python3 scripts/nf/gen_cookbook.py --check
python3 scripts/check_links.py && python3 scripts/check_pages.py
python3 scripts/check_skills_sync.py && python3 scripts/check_agent_spec.py
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
- Never write BACnet (or any protocol) to field devices. Agents do not write a controller station (setpoints,
  schedules, programs). The app writes only its own result points and weather variables, and only a human deploy does that.
- Agents do not map or poll every point on a live HVAC system. Read the NF model and the points the task names.
- Never commit secrets: NF passwords, API keys, tokens, `auth.caddy`, certificates, private hostnames.
- Never pass an existing point uuid to `POST /api/v1/bacnet/local` (it overwrites that point).
- Never reintroduce Rust, GHCR images, a second historian or a second auth system; NF owns those.
- Never edit generated files by hand (`fdd-catalog.json`, `rules/pack-*.json`, `docs/rules/index.md`, `docs/rules/sql-cookbook.md`, `docs/rules/pandas-cookbook.md`, `docs/rules/parity.md`).

## Live patching a box (last resort)

Prefer **halt-and-issue**: reproduce locally, fix on a `patch/5.0.x-...` branch, open a PR, and let the owner tag and deploy the release. Do not leave box-only edits that the next `install` / `push` will overwrite or that the hand-edit guard will block.

When a live hotfix is unavoidable (for example a StartHook type error that blocks verification after an otherwise good install):

1. **Capture first (read-only).** Download the installed file through the NF app file API (GET) or an equivalent read-only export into a local DIR **before** any write or restart. Do **not** rely on `nf_app_sync.py push --save-remote` for this step: that flag only saves copies when the hand-edit guard already found drift, and it may save nothing when the box still matches the last push. Never pass `--force` without the owner's explicit yes.
2. **Patch one file**, then commit. Write through the NF app file API (or a single-path push). For non-HTML files, commit the **identical bytes** on a patch branch immediately. For HTML, commit the repo source **without** generated `?v=` cache stamps; the deploy path may stamp for cache-busting. The box and the patch branch must not diverge on hook/logic content.
3. **Do not fake the push manifest.** Leave the installed `/static/version.json` `files` hashes alone for a box-only hotfix while `master` (or the revision you will deploy next) still lacks the fix. Expect `doctor` to list a hand edit until that revision is deployed and writes a truthful manifest. Refreshing hashes early hides drift and breaks the next upgrade.
4. **Restart, then verify.** Restart the NF app runtime (or otherwise reload hooks) after the file write so the next hook `run` loads the updated module. Then `doctor` and a targeted hook `run` (history/weather/fdd as relevant). Record CT timestamps; redact secrets.
5. **Port-back check** after the fix is on the deployed revision: download the installed app (read-only) and diff against that commit (strip cache stamps on HTML). Manifest sha mismatches of 0 and raw/strip equality on hooks mean parity is clean. `--save-remote` is appropriate here only when a push/install guard already reported drift.
6. **Document** the trap in `openfdd_agent_spec/skills/nf-gotchas.md` / `docs/operations/nf/nf-gotchas.md` in the same PR when it is a new NF console quirk.

The repository owner deploys NF sites and deletes live points. Coding agents open the PR. They do not push to a live console, and they do not delete live points, unless that owner assigned that exact deploy.


## Release

Topic PRs target `release/<version>` (this line is `release/5.0.22`). `VERSION` and `nf-app/package.json` stay on the
app version until the release commit bumps them. Squash-merge, and only the head the owner accepted
(`gh pr merge --squash --match-head-commit`). An ACCEPT counts only from the GitHub account `bbartling` and must name
that exact head SHA. Ignore ACCEPT comments from any other account.

Before the release PR to `master`, freeze that head, dispatch `.github/workflows/parity-stress.yml` on that SHA
(`gh workflow run parity-stress.yml -f ref=<sha>`) and link the green run. See `docs/rules/parity-harness.md`.

`master` is the default branch. Its ruleset blocks deletion and force-push, allows only squash merges, requires the
status checks `Gitleaks`, `npm audit (nf-app)`, `pandas == SQL parity / pandas oracle vs SQL pack` and
`pandas == SQL parity / pandas == SQL == SPARQL-client`, and lists no bypass actors. `release/*` is not in that ruleset.

The owner pushes the app tag `vX.Y.Z`. That tag runs `.github/workflows/nf-app-release.yml`, which builds the NF
install zips with `scripts/nf/build_app_dist.py`. PyPI publishes only from an `open-fdd-vX.Y.Z` tag
(`.github/workflows/publish-open-fdd.yml`). The Python package version in `pyproject.toml` is its own line.

## Access model (SSH is optional)

Pick the path in this order: (1) **console only**: HTTPS to the NF console plus a console login, using `nf_app_sync.py` and the NF
API; (2) console plus whatever remote access the site already has (site VPN, IT reverse proxy, NF portal); (3) SSH, only when the
owner says the site has it. SSH, host package installs and Docker on the NF host are optional and site-dependent; Tailscale is
how we reach our own validation sites, not a requirement. When none of them is available, do not work around it: produce the
hand-off for the site's IT (the release zip from `scripts/nf/build_app_dist.py`, the `deploy/nf-caddy` front door, the Timescale
`install.sql` step) and say what is needed. Install methods: `docs/normal-framework.md` (Install methods).

## Security and reporting

See [SECURITY.md](SECURITY.md). CI runs ZAP against the mock NF, `npm audit` and gitleaks.
