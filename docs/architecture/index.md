---
title: Architecture
layout: default
nav_order: 3
has_children: true
permalink: /architecture/
---

# Architecture

Open-FDD is a **container stack** (central / Streamlit UI / fieldbus / mqtt / mcp) with Arrow historian, DataFusion SQL FDD, and Project Haystack semantic model.

| Topic | Document |
|-------|----------|
| [ADR-001 React/Rust](adr-001-react-rust-modernization.html) | Phase 1 SPA + Python-exit decision |
| [Services](services.html) | Stack images and compose roles |
| [Data flow](data-flow.html) | Drivers → model → historian → FDD → UI |
| [Storage & DataFusion](storage-and-datafusion.html) | Feather historian and SQL rules |
| [DataFusion-first](datafusion-first.html) | Pandas policy and production SQL rule |
| [Job workspaces](job-workspaces.html) | Persistent analysis Jobs under `workspace/jobs/` |
| [Analytics boundary](analytics-boundary.html) | Typed DF analytics vs Streamlit |

Modernization ledgers: [React / Rust migration](../migration/react-rust/).
