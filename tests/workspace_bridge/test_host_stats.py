from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.host_stats import (  # noqa: E402
    _memory_payload,
    _read_linux_meminfo,
    _swap_payload,
    collect_host_stats,
)
from openfdd_bridge.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_memory_payload_from_meminfo():
    meminfo = {
        "MemTotal": 8 * 1024**3,
        "MemAvailable": 3 * 1024**3,
        "SwapTotal": 4 * 1024**3,
        "SwapFree": 4 * 1024**3,
    }
    mem = _memory_payload(meminfo)
    assert mem["available"] is True
    assert mem["total_bytes"] == 8 * 1024**3
    assert mem["available_bytes"] == 3 * 1024**3
    assert mem["percent_used"] == 62.5

    swap = _swap_payload(meminfo)
    assert swap["percent_used"] == 0.0


def test_collect_host_stats_shape():
    stats = collect_host_stats(cpu_sample_interval=0.02)
    assert stats["ok"] is True
    assert "host" in stats
    assert stats["host"]["hostname"]
    assert stats["cpu"]["logical_cores"] >= 1
    assert "memory" in stats
    assert "swap" in stats
    storage = stats["storage"]
    assert storage.get("available") is True
    assert storage["path"]
    assert storage["total_bytes"] > 0
    assert "percent_used" in storage
    assert "feather_bytes" in storage
    assert "feather_max_gib" in storage
    assert isinstance(stats["disks"], list)
    ollama = stats["ollama"]
    assert isinstance(ollama, dict)
    assert "api_ok" in ollama
    assert "base_url" in ollama


def test_read_linux_meminfo_on_linux():
    if not Path("/proc/meminfo").is_file():
        pytest.skip("no /proc/meminfo")
    meminfo = _read_linux_meminfo()
    assert meminfo is not None
    assert meminfo["MemTotal"] > 0


def test_host_stats_api(client: TestClient):
    r = client.get("/api/host/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["host"]["platform"]
    assert "cpu" in body
    assert body["storage"]["available"] is True
