---
name: driver-openmeteo-weather
description: "Configures Open-Meteo weather ingest into feather storage for outdoor air and weather-gated FDD rules. Use when drivers include openmeteo or operators need OAT/humidity/wind series."
---

# Open-Meteo weather driver

## Prerequisites

Bridge `GET/POST /config/weather`, `POST /ingest/weather`. Feather storage per site.

## Quick start

Store API params (lat/lon, variables) in config JSON; ingest job writes weather source shards.

## Verification

Ingest one site; confirm weather columns in timeseries query.

## Reference

Legacy: `open_fdd/platform/drivers/weather_driver.py`, gateway weather config routes.
