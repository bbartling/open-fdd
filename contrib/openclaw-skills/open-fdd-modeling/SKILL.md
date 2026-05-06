---
name: open-fdd-modeling
description: AI-assisted Open-FDD data model export, LLM review, validate, import, and SPARQL checks via the desktop bridge.
---

# Open-FDD data modeling (OpenClaw)

## When to use

- Operator wants to **adjust sites, equipment, or points** with help from the assistant.
- You have (or can fetch) **model JSON** from the Open-FDD bridge and need a safe **edit → validate → import** loop.

## Preconditions

- Bridge running (default `http://127.0.0.1:8765`; from Docker use `http://host.docker.internal:8765` per runbook).
- Use **`GET /docs`** or **`/openapi.json`** for exact request bodies on this revision.

## Workflow

1. **Export** — `GET {bridge}/model/export` — capture current JSON.
2. **Draft changes** — Propose edits only in structured JSON the bridge accepts; prefer minimal diffs and preserve `site_id` / UUIDs unless the operator asks to create new entities.
3. **Validate** — `POST {bridge}/model/validate` with the draft payload when available; otherwise use import validation errors from `POST /model/import` response.
4. **Import** — `POST {bridge}/model/import` only after operator confirmation.
5. **Graph check** — Optional `POST {bridge}/data-model/sparql` with a small `SELECT` to sanity-check Brick/TTL expectations.

## Safety

- Never invent **API keys** (BACnet DIY, OpenClaw gateway token, etc.); read from operator env or bridge config endpoints if documented.
- On failure, return HTTP status, response body snippet (redacted), and the **curl** the operator can replay.

## References

- Repository: `docs/modeling/index.md`, `docs/open-fdd-claw-architecture.md`, `scripts/OPENCLAW_RUNBOOK.md`.
