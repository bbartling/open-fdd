---
title: Port notes
parent: NF operations
nav_order: 7
---

# Port notes

These pages and tools were carried over from a private lab-notes repository that is being retired. This page
records what moved where, what was deliberately left behind, and what to watch for.

## What moved

| Source topic | Now |
|---|---|
| Caddy front door with NF on loopback (plain HTTP and self-signed HTTPS variants) | already in [`deploy/nf-caddy`](https://github.com/bbartling/open-fdd/tree/master/deploy/nf-caddy) (a superset); merged the differences: `APP_ID` for the `:80` redirect, `CA:TRUE` certificate extensions, rationale, safe order, verify, clients, roll back in [Front door](front-door-caddy.html) |
| LAN HTTPS findings (`TAILSCALE_HTTPS` breaks hooks and the portal) | [Front door](front-door-caddy.html), [NF gotchas](nf-gotchas.html) |
| Tag-driven portal and LAN sensor, history, BACnet-validate scripts | [`scripts/nf/tools/`](https://github.com/bbartling/open-fdd/tree/master/scripts/nf/tools), shared helpers split into `nf_common.py` |
| BACnet validation from a PC, port 47808 clashes | [BACnet validation](bacnet-validate.html), skill `bacnet-validate` |
| Haystack tagging notes | [Haystack tagging](haystack-tagging.html), pointers from [Modeling](../../modeling.html) |
| NF compose same-tag pull and upgrade notes | [Upgrade NF](nf-upgrade-compose.html) |
| Product findings that are still true on 3.10 | [NF gotchas](nf-gotchas.html), skill `nf-gotchas` |
| Edge-box architecture diagrams | [Architecture](../../architecture.html) (three diagrams; the big picture was already there) |
| Enhancements backlog | [Development](../../development.html), Roadmap ideas |
| BACnet site scanner (CSV + RDF) | [`tools/bacnet-scan/`](https://github.com/bbartling/open-fdd/tree/master/tools/bacnet-scan) (`bacnet_site_scan.py` only) |
| Lite versus full guidance | [Lite or full](lite-vs-full.html) |

## What was left out, and why

- The two dashboard apps from the lab (`nf-bench-viz`, `open-fdd-edge`) and their hook backups: superseded by
  Lite and the full app. No UI pattern was missing from Lite.
- A FastAPI + React sidecar dashboard with its CI and deploy scripts, and one-off helper scripts for it (poll
  period, quality-rule upserts, a built-in-dashboard writer using internal config keys): a different product that
  guesses at NF internals. The rules in its design note live on in `AGENTS.md`: discover everything from NF.
- Findings that read as episode history, support-bot notes, chat-thread pointers, YouTube and tutorial-review
  notes, bench-specific IO assignments, paid-support queue and partner access: personal or operational, not
  reusable.
- The older `discover-objects-*.py` scanners and `analyze-writes.py`: the single `bacnet_site_scan.py` replaced
  them. `analyze-writes.py` reads the older scanner's Turtle (`urn:bacnet-scan:` namespace); the new scanner writes
  `urn:bacnet-site-scan:`, so the two do not fit together without a change.
- Scan outputs from the lab network, and a copy of the pull-request README for an upstream library.
- `tools/rdf-check`: open-fdd already has a newer, fixture-based version. The lab version's live-NF mode (run the
  page's `model.js` against a real NF) is noted as a roadmap idea.
- DIY Cloudflare tunnel steps and lab-specific remote-access notes: Normal Online is the supported remote path
  (see [Architecture](../../architecture.html)).

## Corrections made while porting

- The old findings said NF has no zone/outside point classes and no way to name them. NF 3.10 lists hundreds of
  classes (`GET /api/v1/equipment/classes?pageSize=1000`); the ontology note was rewritten accordingly.
- The old scripts looked for settings next to themselves and in a private folder, resolved the CA file relative to the
  repo, and defaulted the history tool to one bench's tags. The ported tools read the environment or `--env FILE`
  only, and the history tool requires explicit markers.
- `nf_bacnet_validate.py` imported bacpypes3 at the top, so even `--help` failed without it; it now degrades with a
  clear message.
- Install docs said the full edition needs PGlite at 4 GB; the TimescaleDB profile with the 100 GB cap now has its
  own row ([Install](../../install.html)).

## Watch for

- Both editions ship a weather hook that writes the same global-variable labels. Run one edition per NF.
- `deploy/nf-caddy`'s `:80` redirect now follows `APP_ID` (default `open-fdd`); on a Lite box set `open-fdd-lite`.
- Any pasted NF environment output (`nf version`, `docker logs`) can contain the cloud-backup URL with its write
  signature; see the [gotcha](nf-gotchas.html).
- `scripts/nf/tools/` are validated by `py_compile` and `--help` only; they were not run against a live NF as part of
  the port. Run `nf_portal_sensors.py` against a test box once before relying on them.
