---
title: Continuous context backup loop
parent: Operations
nav_order: 8
---

# Continuous context backup loop

This is the non-site-specific process for making the virtual operator improve over time without turning the repo into one building's notebook.

## What gets backed up

Back up only **durable, reusable process knowledge**:

- operator heuristics
- failure classification rules
- dashboard expectations
- overnight review discipline
- SPARQL/query patterns that discover site context from the model
- how to separate product bugs from setup/auth drift

## What does not get backed up

Do not back up:

- bearer keys or API keys
- raw `.env` contents
- device pairing secrets
- local SQLite conversation history
- one-off private notes that should stay local
- hard-coded site assumptions that belong in the Open-FDD model instead

## Trigger for an update

During overnight review, update the repo when any of these are true:

- the process changed materially
- the operator framework got smarter
- a failure pattern should be remembered by future clones
- a new query pattern or heuristic is now part of normal operation
- the dashboard or alert contract changed

## Update sequence

1. Distill the lesson from local context
2. Put it into the best durable home:
   - docs
   - query template under [`openclaw/bench/sparql/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/sparql/README.md)
   - YAML policy file (e.g. [`config/ai/operator_framework.yaml`](../../config/ai/operator_framework.yaml))
3. Commit the change professionally
4. Push to GitHub
5. Rebuild/publish the docs PDF when the docs set changed materially

## Why this matters

This makes the OpenClaw/Open-FDD operator behave more like a continuously improving engineering system and less like a chat session with amnesia.

The repo becomes the transferable brainstem. The live Open-FDD model remains the site-specific truth.
