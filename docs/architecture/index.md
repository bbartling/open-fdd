---
title: Architecture
layout: default
nav_order: 3
has_children: true
permalink: /architecture/
---

# Architecture

Open-FDD is a **Rust edge application** with a React web UI, Arrow historian, DataFusion SQL engine, and Project Haystack semantic model.

| Topic | Document |
|-------|----------|
| [Services](services.html) | Bridge, commission, Haystack gateway, compose profiles |
| [Data flow](data-flow.html) | Drivers → model → historian → FDD → dashboard |
| [Storage & DataFusion](storage-and-datafusion.html) | Feather historian and SQL rules |
