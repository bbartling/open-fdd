---
title: Install the NF app
nav_order: 2
---

# Install Open-FDD on NF

Open-FDD is an app for the Normal Framework (NF). It reads the modeled site, equipment, points, and history from NF.
It does not need a separate login or historian. Choose Full for FDD and larger hosts, or Lite for smaller hosts.

## Choose Full or Lite

| Edition | App id | Includes | Typical resources |
|---|---|---|---|
| Full | `open-fdd` | SQL FDD, charts, export, RDF/SPARQL, and FDD, weather, and SPARQL hooks | SQLite on smaller hosts; PGlite or Timescale on larger hosts |
| Lite | `open-fdd-lite` | dashboard, charts, export, weather hook, and RDF | about 1 GB RAM; no FDD or Timescale |

Do not install both editions on a constrained box. Build, test, and run installer commands from a PC; NF runs the
installed app and hooks.

## Choose an install route

### Recommended: sync from a workstation

Clone or download the repository on a workstation that can reach the NF console. The installer uses Python 3 and the
standard library; it does not build the app. Prepare an environment file outside the repository:

```text
NF_CONSOLE_URL=<reachable-NF-console-url>
CONSOLE_USERNAME=<console-user>
CONSOLE_PASSWORD=<console-password>
```

Use the local console login. A Normal Online API key is read-only and cannot install files or hooks. Protect the env
file and do not put credentials in command-line arguments.

```bash
python3 scripts/nf/hooks/nf_app_sync.py --env <protected-env-file> doctor nf-app/app.json
python3 scripts/nf/hooks/nf_app_sync.py --env <protected-env-file> install nf-app/app.json
```

Use `lite/app.json` for Lite. To install or upgrade, `install` checks connectivity, syncs app files and hook
definitions, installs app dependencies when needed, restarts the app, and verifies scheduled hooks. It refuses to
overwrite hand-edited files unless you explicitly choose the force option. Read the diff first.

### Console-first or managed workstation

When a workstation cannot run the installer, an authorized operator can use the NF MCP console tools to create the
app, upload every file listed in `nf-app/app.json` or `lite/app.json`, deploy each declared hook, install
dependencies, and restart the app. This is a manual alternative, not a one-click app-store install. A partial upload
is not a valid install.

For a non-SSH or restricted-IT environment, ask the NF administrator to provide a temporary supported console route
or to run the installer from an approved workstation. Hand off the edition, release or commit to pin, protected
credentials location, required API access, and verification checklist. Do not ask IT to open field-device protocols
or expose the console to the public internet. See [Security](security.html).

## Reach NF safely

The workstation must reach the NF console over the site LAN, an approved VPN, or a temporary SSH forward. If the
console is behind a TLS proxy, trust its certificate with the installer CA-file or certificate-pin option; do not
disable certificate verification. Use the front-door URL that the workstation can reach and confirm that the proxy
and NF accept the same console login. Plain HTTP is for a trusted local network only. The portal API key path is for
reads and is not a deployment route.

## Timescale option and schema preflight

Full can use SQLite, PGlite, or TimescaleDB. Lite does not use Timescale. For Timescale, configure the app option
`timescale` as a JSON string or PostgreSQL URL, then apply `nf-app/timescale/install.sql` using a database installer
role. Give the hooks a separate least-privilege runtime role. See the
[`nf-app/timescale` guide](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).

The installer checks the selected Timescale schema before upgrading. If the schema is behind, apply
`nf-app/timescale/install.sql` as the database installer role, then repeat the check. The check runs `psql` from the workstation
using the configured connection details. If the option names `localhost`, `127.0.0.1`, or `::1`, that address
refers to the NF host; it does not refer to a remote workstation. In that case the installer stops before connecting.
Set `NF_TIMESCALE_PREFLIGHT_DSN` in the protected environment to a reachable endpoint for the same database, such
as a temporary approved forward, or run the CLI on the NF host. Keep credentials out of the command line. Lite,
SQLite, and PGlite skip this Timescale preflight.

## Model and verify

Tag sites, equipment, points, and units in NF; Open-FDD has no per-site configuration. Points need history for charts
and rules. The FDD page lists missing required roles. See [Modeling](modeling.html) and [Units](units.html).

After install, check:

- `doctor` reports a clean install and the expected engine/schema state.
- The dashboard and charts load; Full FDD reports current results.
- RDF export has no dangling references.
- The weather hook has coordinates from its app option or modeled site.
- If using the BACnet server, validate point mappings before enabling its output.

## Upgrade, pin, and remove

Before an upgrade, run `doctor` and review the target release notes. Fetch or check out the exact release tag or commit
you intend to deploy, then run `install` from that tree. Keep the edition pinned to the same reviewed revision on
each site; do not deploy floating `master` in a controlled rollout.

`install --remove-old` lists predecessor apps; add `--yes` only when you intend to remove those apps. It does not
delete hook-created history or points. Run `uninstall` to remove the current app after reviewing its dry-run output.
Back up NF configuration before changing the host itself. Upgrading the NF framework is a separate operation; follow
the framework's release instructions and verify its console before installing Open-FDD. App uninstall is not a
substitute for an NF backup.

## Hooks

Full schedules `fdd` hourly and `weather` every 20 minutes; `sparql` is on request. Lite schedules `weather`
only. Hook runs and results appear in NF. The app writes its own result points and weather variables; it does not
write to HVAC controllers or other field devices.

## Further help

- [Modeling](modeling.html): classes, markers, roles, and point units.
- [API reference](fdd-data-access.html): read NF points, results, and history.
- [Timescale guide](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale): schema, roles, and retention.
- [Development](development.html): local mock, tests, and generated packs.
