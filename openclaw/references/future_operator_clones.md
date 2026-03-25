# Future: OpenClaw clones on live HVAC / Open-FDD sites

## What varies per deployment

- **Brick / RDF graph** — site, equipment, points, namespaces.
- **HVAC archetype** — chillers vs RTUs vs district systems; rules and SPARQL differ.
- **BACnet** device inventory and credentials.
- **Operator workflows** — alarms, schedules, ticketing integrations (future).

## Unknown / to be defined

- **Gold standard** “day-one” skill pack for a new clone (minimal vs full operator).
- How much lives in **repo `openclaw/`** vs **per-site git** vs **OpenClaw workspace `memory/`**.
- **Secrets** handling (never in `issues_log` or committed env files).

## What to do now

1. Keep **`open-fdd/openclaw/SKILL.md`** and **`references/`** as the **versioned** core.
2. Append **site-specific** lessons to `issues_log.md` during pilots; promote stable patterns into this file or `docs/openclaw_integration.md`.
3. When a pattern repeats across two sites, open a **GitHub issue** to codify it (checklist or script under `openclaw/scripts/`).

This file is intentionally incomplete — update as real deployments teach us.
