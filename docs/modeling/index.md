---
title: Data modeling & platform docs
nav_order: 7
has_children: false
---

# Data modeling and full-stack docs

**Brick, 223P, SPARQL, CRUD APIs, Docker Compose, and lab automation** for Open-FDD as a **deployed platform** now live in a separate repository:

**[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**

That site documents how the stack uses this **`open-fdd`** PyPI package **under the hood** (`RuleRunner`, YAML rules, pandas).

---

## In *this* repository (rules engine only)

- **[Column map resolvers](../column_map_resolvers)** — map **Brick**, **Haystack**, **DBO**, **223P**, or vendor labels to DataFrame columns (dict, manifest, composite resolvers).
- **[Expression rule cookbook](../expression_rule_cookbook)** — fault logic on pandas, including schedule and weather gates via **`params.schedule`** / **`params.weather_band`**.
- **`examples/column_map_resolver_workshop/`** — runnable **ontology-agnostic** demo (`simple_ontology_demo.py`).

Semantic modeling and TTL/SQL integration are **not** part of the **`open-fdd`** wheel; keep RDF/graph work in your services or in **open-fdd-afdd-stack** as documented there.

---

## AI-assisted modeling workflows

For the full **OpenClaw + Codex OAuth + gateway HTTP** integration picture, see **[Open FDD Claw architecture](open-fdd-claw-architecture)** and [`scripts/OPENCLAW_RUNBOOK.md`](https://github.com/bbartling/open-fdd/blob/master/scripts/OPENCLAW_RUNBOOK.md) Phase 0.

For AI-assisted data modeling (OpenClaw, ChatGPT, or human-in-the-loop review), use a simple loop:

1. Export model JSON from your backend (`/model/export` or stack export endpoint).
2. Review and revise with an LLM (OpenClaw agent or ChatGPT web UI).
3. Validate the edited JSON before import.
4. Import JSON back to backend (`/model/import`) and re-run SPARQL/rules checks.

The same flow works for:

- **OpenClaw agents** running local automation loops.
- **ChatGPT online interface** where a human copies export JSON in and validated JSON out.
- **Hybrid** workflows where AI drafts and human confirms before import.

For robust prompts, import schema guidance, and operator-safe pre-flight checks, see:

- **[AFDD stack modeling docs](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs/modeling)**
- **[LLM workflow page](https://bbartling.github.io/open-fdd-afdd-stack/modeling/llm_workflow)**

---

## Local HTTP gateway note (open-fdd repo)

The FastAPI **gateway** (`open_fdd.gateway`, CLI `open-fdd-gateway` / `open-fdd-desktop-bridge`) supports agent-friendly backend operations such as:

- model export/import/validate,
- SPARQL query endpoints (`/data-model/sparql`, `/data-model/sparql/upload`),
- timeseries bounds/query over Feather data,
- weather/onboard ingest and ML training routes.

This enables OpenClaw-style local assistants to do data modeling, retrieve and join data in pandas/Feather workflows, run faults, and iterate with a human operator.
