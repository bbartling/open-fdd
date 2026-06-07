#!/usr/bin/env python3
"""Standalone OpenWeatherMap poll — mirrors workspace/json_api.env.local usage.

Copy workspace/json_api.env.example → workspace/json_api.env.local, set
OPENWEATHER_API_KEY, then:

  python3 scripts/openweather_json_api_example.py

To register the three historian points via the bridge API (integrator token):

  python3 scripts/openweather_json_api_example.py --register --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.json_api_env import expand_env_string, load_json_api_env  # noqa: E402
from openfdd_bridge.json_api_store import OPENWEATHER_URL  # noqa: E402


def _load_env() -> None:
    path = REPO / "workspace" / "json_api.env.local"
    if path.is_file():
        os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
        load_json_api_env(reload=True)
    else:
        print(f"Missing {path} — copy workspace/json_api.env.example first.", file=sys.stderr)
        sys.exit(1)


def fetch_weather() -> dict:
    _load_env()
    url = expand_env_string(OPENWEATHER_URL)
    if "${" in url:
        print("Unresolved placeholders in URL — set OPENWEATHER_API_KEY in json_api.env.local", file=sys.stderr)
        sys.exit(1)
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    units = os.environ.get("OPENWEATHER_UNITS", "imperial")
    symbol = "°F" if units == "imperial" else "°C" if units == "metric" else "K"
    city = os.environ.get("OPENWEATHER_CITY", "Madison,WI,US")
    main = data.get("main") or {}
    weather = (data.get("weather") or [{}])[0]
    print(f"Weather in {city}:")
    print(f"  web-oat-t: {main.get('temp')}{symbol}")
    print(f"  web-rh: {main.get('humidity')}%")
    print(f"  web-weather-desc: {weather.get('description')}")
    return data


def register_bundle(base: str, user: str, password: str) -> None:
    _load_env()
    login = httpx.post(f"{base.rstrip('/')}/api/auth/login", json={"username": user, "password": password}, timeout=15.0)
    login.raise_for_status()
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    res = httpx.post(
        f"{base.rstrip('/')}/api/json-api/presets/openweather",
        headers=headers,
        json={"poll_interval_s": 300, "enabled": True, "poll_once": True},
        timeout=30.0,
    )
    res.raise_for_status()
    print(json.dumps(res.json(), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenWeatherMap JSON API driver example")
    parser.add_argument("--register", action="store_true", help="Register bundle via bridge API")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="Bridge base URL")
    parser.add_argument("--user", default=os.environ.get("OFDD_INTEGRATOR_USER", "integrator"))
    parser.add_argument("--password", default=os.environ.get("OFDD_INTEGRATOR_PASSWORD", ""))
    args = parser.parse_args()
    if args.register:
        if not args.password:
            print("Set OFDD_INTEGRATOR_PASSWORD or pass --password", file=sys.stderr)
            sys.exit(1)
        register_bundle(args.base, args.user, args.password)
    else:
        fetch_weather()


if __name__ == "__main__":
    main()
