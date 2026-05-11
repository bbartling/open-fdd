---
name: driver-bacnet-ingest
description: "Builds BACnet polling ingest and headless driver tooling for site timeseries. Use when drivers include bacnet or operators integrate field controllers."
---

# BACnet ingest driver

## Prerequisites

Bridge `GET/POST /config/bacnet`, `POST /ingest/bacnet`, driver health export.

## Quick start

Configure device/object map; scheduled poll writes bacnet source feathers.

## Verification

`GET /config/drivers/health`; smoke poll interval script pattern from legacy headless driver.

## Reference

Legacy: `open_fdd/platform/drivers/`, `open-fdd-headless-bacnet` CLI (retired).
