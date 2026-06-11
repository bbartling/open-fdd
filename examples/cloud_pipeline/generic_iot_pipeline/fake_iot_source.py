"""Fake IoT telemetry source — replace with MQTT, DynamoDB stream, etc."""

from __future__ import annotations

from typing import Any, Iterator


def iter_rows(site_id: str, n: int = 50) -> Iterator[dict[str, Any]]:
    for i in range(n):
        yield {
            "site_id": site_id,
            "timestamp": f"2024-06-01T10:{i % 60:02d}:00Z",
            "SAT": 55.0 + (i % 10),
        }
