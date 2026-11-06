---
title: Development
nav_order: 11
---

# Development

Everything runs on a normal PC; no NF box is needed.

## Repo map

| Path | What |
|---|---|
| `nf-app/` | **The full app.** `app.json` manifest, `static/` UI, `hooks/` (`fdd`, `weather`, `sparql`), `rules/` (SQL packs, role overrides), `rcx-parity.json`, `dev/` (mock NF), `tests/`, `types/` |
| `lite/` | Open-FDD Lite: the small-box edition ([Lite](lite.html)) |
| `sql/fdd/` | The FDD math: 77 Postgres SQL rules, registry, role map and tuning catalog; the single source the packs are built from |
| `scripts/nf/` | Build the rule catalog and SQL packs, `gen_rule_docs.py`, deploy with `hooks/nf_app_sync.py` |
| `deploy/nf-caddy/` | Optional Caddy front door ([Install](install.html)) |
| `tools/rdf-check/` | Turtle checker (Oxigraph + rdflib) |
| `open_fdd/`, `tools/python_oracle/`, `tests/parity/` | PyPI package with the pandas reference rules, and the pandas == SQL parity harness |
| `docs/` | This site (Jekyll, Just the Docs) |

## Run it locally

```bash
node nf-app/dev/mock-nf.mjs          # http://127.0.0.1:8765/api/v1/apps/static/open-fdd/
```

The mock serves `nf-app/static` at the NF app URL and answers the NF API from a deterministic synthetic two-site
building (air handlers, VAVs, chiller plant, boiler, meters, weather, FDD result points with faults). Points are
tagged the way a real site is, so every view binds. Read-only.

## Test

```bash
node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs    # unit, parity, engines, RDF, SPARQL, export
cd nf-app && npm ci && npm run typecheck                      # tsc --noEmit over the JSDoc-typed JS
python3 scripts/nf/build_rule_catalog.py --check              # catalog matches sql/fdd
python3 scripts/nf/build_sql_pack.py --check                  # packs match sql/fdd
python3 scripts/nf/gen_rule_docs.py --check                   # docs/fdd-rules.md matches the catalog
```

CI (`nf-app-ci.yml`) runs the same checks plus the RDF check.

## Add a chart

Charts are RCx views registered in one of the view modules (`rcx-overview.js`, `rcx-presets.js`, `fdd-plots.js`,
`energy.js`):

```js
rcxView({
  id: "economizer-delta", group: "Air handlers", title: "Economizer: OAT - MAT",
  kinds: ["ahu"],                                   // equipment kinds from fdd-catalog.json; [] = any
  roles: { required: ["oa_t", "mat"], optional: ["rat"] },
  scope: "equip",                                   // or "site"
  render: async (el, ctx) => { /* draw into el */ },
});
```

- Use role names from `nf-app/static/fdd-catalog.json`; never reference a site, equipment name or point uuid.
- Show faults only with `rcxWithFaultLane(option, [{ name, data }])` ([Charts](charts.html)).
- Work in SI; convert for display with `ofddUnits` ([Units](units.html)).
- Register it in `nf-app/rcx-parity.json` and add a test.

## Add a rule

1. Write the Postgres SQL in `sql/fdd/postgres/rules/` and add the rule to `sql/fdd/registry.yaml` (roles,
   parameters with SI units, confirm time). New roles go in `sql/fdd/role_map.json` (or the NF-class overrides in
   `nf-app/rules/role_overrides.json`).
2. `python3 scripts/nf/build_rule_catalog.py` and `python3 scripts/nf/build_sql_pack.py` rebuild the catalog and both packs.
3. `python3 scripts/nf/gen_rule_docs.py` rebuilds [FDD rules](fdd-rules.html).
4. `node --test nf-app/tests/engines.test.mjs`: the SQLite pack must match Postgres on every rule.
5. The pandas reference must agree with SQL (next section).

## pandas == SQL parity

`open_fdd/` holds pandas reference implementations of the rules. A parity harness
([`tests/parity/`](https://github.com/bbartling/open-fdd/tree/master/tests/parity), workflow `parity.yml`) runs the pandas oracle
and the SQL pack on synthetic data and requires the same answers. It is being finalized; see its workflow for the current command.

## Roadmap ideas

Not built; each is small enough for its own slice.

- **Headless RDF on Lite hosts.** The full edition has the `sparql` hook (CONSTRUCT returns Turtle with no browser
  open). Lite builds Turtle only in the page, so nothing is produced when nobody opens it. Options: a timer on
  another host that runs the export against the open read-only routes and keeps the last file that passes
  `tools/rdf-check/check_ttl.py` (extend `gen_ttl.js` with a live-NF mode); or a Lite hook, which first needs an answer
  to whether a hook may write a file NF serves from the app's `static/` folder. Ask Normal whether NF can export
  Brick or RDF itself; an NF-produced export would be more authoritative than ours.
- **More standard RDF.** Today's `phIoT` namespace is a simplified Haystack form and the standard-tag list is
  hand-picked; load Project Haystack's published defs and align the namespaces before the files leave one site.
  Run `check_ttl.py` in CI against a saved model snapshot.
- **Longer history on small hosts.** NF's Redis keeps about 7 days; for more, configure NF's northbound
  Postgres/TimescaleDB integration (see [Lite or full](operations/nf/lite-vs-full.html)) or export history on a schedule.
- **Pin the Clerk domain.** Tighten the CSP `script-src` for the portal sign-in script to the exact Clerk domain
  instead of `https:`.

## Conventions

- Small, reviewable PR slices; one concern each.
- No inline scripts or styles, no CDN at runtime (strict CSP, see [Security](security.html)).
- Vendored libraries are pinned and never younger than two weeks (see the table in `nf-app/README.md`).
- Never commit secrets: env files live outside git.
