---
title: Operator framework
parent: Operations
nav_order: 4
---

# Operator framework

The canonical machine-readable framework lives at `config/ai/operator_framework.yaml`.

This page explains how to use it.

## Intent

Provide a portable operator reasoning contract for Open-FDD automation:

- source-of-truth ordering
- mode detection (`TEST_BENCH` vs `LIVE_HVAC`)
- seasonal reasoning bias
- failure classification
- overnight improvement loop

## Usage

- Humans: review this page + YAML before changing automation behavior.
- Agents: treat YAML as policy contract and derive site specifics from live Open-FDD model/data.
- Repos: keep this file generic; do not hard-code one-site tribal assumptions.

