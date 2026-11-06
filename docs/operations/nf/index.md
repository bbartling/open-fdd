---
title: NF operations
nav_order: 13.5
has_children: true
---

# NF operations

Runbooks for the Normal Framework (NF) box that Open-FDD runs on. They are generic: no site, hostname or
credential is baked in, and every command uses placeholders such as `192.0.2.10` and `<nf-host>`.

| Page | Read it when |
|---|---|
| [Lite or full](lite-vs-full.html) | choosing which edition a host should run |
| [Front door (Caddy)](front-door-caddy.html) | the LAN needs a login in front of NF, or HTTPS |
| [Upgrade NF (compose)](nf-upgrade-compose.html) | changing NF's image tag or pulling the same tag |
| [Haystack tagging](haystack-tagging.html) | points exist in NF but the dashboard or rules do not bind them |
| [BACnet validation](bacnet-validate.html) | proving NF's values match what is on the BACnet wire |
| [NF gotchas](nf-gotchas.html) | something in NF behaves oddly; check here before debugging |
| [Port notes](PORT_NOTES.html) | where these pages came from, and what was left out |

Command-line tools for these runbooks are in
[`scripts/nf/tools/`](https://github.com/bbartling/open-fdd/tree/master/scripts/nf/tools); the BACnet site scanner is
[`tools/bacnet-scan/`](https://github.com/bbartling/open-fdd/tree/master/tools/bacnet-scan).
