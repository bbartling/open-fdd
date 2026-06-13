"""Home Assistant sensor.rest-style presets for JSON API commissioning."""

from __future__ import annotations

from typing import Any

from .json_api_store import OPENWEATHER_POINTS, OPENWEATHER_URL
from .poll_intervals import poll_interval_choices

# Each preset: one HTTP resource → one or more historian sensors (json_path extractions).
REST_PRESETS: list[dict[str, Any]] = [
    {
        "id": "jsonplaceholder-todo",
        "name": "JSONPlaceholder — todo title",
        "category": "beginner",
        "description": "Free fake REST API — single string field from a todo.",
        "resource": "https://jsonplaceholder.typicode.com/todos/1",
        "method": "GET",
        "sensors": [{"json_path": "title", "label": "todo-title", "units": ""}],
    },
    {
        "id": "jsonplaceholder-user",
        "name": "JSONPlaceholder — user name",
        "category": "beginner",
        "description": "Nested JSON — dot path into address or name.",
        "resource": "https://jsonplaceholder.typicode.com/users/1",
        "method": "GET",
        "sensors": [{"json_path": "name", "label": "user-name", "units": ""}],
    },
    {
        "id": "jsonplaceholder-post",
        "name": "JSONPlaceholder — POST todo",
        "category": "beginner",
        "description": "POST JSON body; read echoed title from response.",
        "resource": "https://jsonplaceholder.typicode.com/todos",
        "method": "POST",
        "body_json": '{"title": "OT bench poll", "userId": 1, "completed": false}',
        "sensors": [{"json_path": "title", "label": "post-title", "units": ""}],
    },
    {
        "id": "dummyjson-product",
        "name": "DummyJSON — product price",
        "category": "demo",
        "description": "Fake storefront API — numeric extraction.",
        "resource": "https://dummyjson.com/products/1",
        "method": "GET",
        "sensors": [{"json_path": "price", "label": "product-price", "units": "USD"}],
    },
    {
        "id": "dummyjson-user",
        "name": "DummyJSON — user full name",
        "category": "demo",
        "description": "Combine first + last via separate sensors on one resource.",
        "resource": "https://dummyjson.com/users/1",
        "method": "GET",
        "sensors": [
            {"json_path": "firstName", "label": "user-first", "units": ""},
            {"json_path": "lastName", "label": "user-last", "units": ""},
        ],
    },
    {
        "id": "httpbin-get",
        "name": "httpbin — GET echo",
        "category": "debug",
        "description": "Request/response echo — inspect headers and origin IP.",
        "resource": "https://httpbin.org/get",
        "method": "GET",
        "sensors": [{"json_path": "origin", "label": "httpbin-origin", "units": ""}],
    },
    {
        "id": "httpbin-headers",
        "name": "httpbin — custom header",
        "category": "debug",
        "description": "Send a custom header; read it back from JSON.",
        "resource": "https://httpbin.org/headers",
        "method": "GET",
        "headers_json": '{"X-OpenFDD-Bench": "1"}',
        "sensors": [{"json_path": "headers.X-OpenFDD-Bench", "label": "httpbin-header", "units": ""}],
    },
    {
        "id": "open-meteo-temp",
        "name": "Open-Meteo — Madison temperature",
        "category": "weather",
        "description": "Real weather API, no API key — current air temperature.",
        "resource": "https://api.open-meteo.com/v1/forecast?latitude=43.07&longitude=-89.4&current=temperature_2m",
        "method": "GET",
        "sensors": [
            {"json_path": "current.temperature_2m", "label": "meteo-temp-c", "units": "degC"},
        ],
    },
    {
        "id": "open-meteo-bundle",
        "name": "Open-Meteo — temp + wind (multi-sensor)",
        "category": "weather",
        "description": "One GET, multiple historian columns (HA json_attributes style).",
        "resource": "https://api.open-meteo.com/v1/forecast?latitude=43.07&longitude=-89.4&current=temperature_2m,wind_speed_10m",
        "method": "GET",
        "sensors": [
            {"json_path": "current.temperature_2m", "label": "meteo-temp-c", "units": "degC"},
            {"json_path": "current.wind_speed_10m", "label": "meteo-wind-kmh", "units": "km/h"},
        ],
    },
    {
        "id": "openaq-london",
        "name": "OpenAQ — London PM2.5",
        "category": "iot",
        "description": "Real air-quality sensor data — latest measurement value.",
        "resource": "https://api.openaq.org/v3/locations/8118/latest",
        "method": "GET",
        "sensors": [{"json_path": "results.0.value", "label": "openaq-pm25", "units": "µg/m³"}],
    },
    {
        "id": "openweather-bundle",
        "name": "OpenWeatherMap — OAT + RH",
        "category": "weather",
        "description": "Dry-bulb and humidity from one URL (30 min poll) — requires OPENWEATHER_API_KEY in json_api.env.local.",
        "resource": OPENWEATHER_URL,
        "method": "GET",
        "requires_env": ["OPENWEATHER_API_KEY"],
        "sensors": [
            {"json_path": spec["json_path"], "label": spec["label"], "units": ""}
            for spec in OPENWEATHER_POINTS
        ],
        "env_note": "Copy workspace/json_api.env.example → json_api.env.local",
    },
]


def list_rest_presets() -> dict[str, Any]:
    categories = sorted({str(p.get("category") or "other") for p in REST_PRESETS})
    return {
        "ok": True,
        "presets": REST_PRESETS,
        "categories": categories,
        "poll_intervals": poll_interval_choices(),
        "ha_reference": "https://www.home-assistant.io/integrations/sensor.rest/",
    }


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    key = str(preset_id or "").strip()
    for preset in REST_PRESETS:
        if preset.get("id") == key:
            return preset
    return None
