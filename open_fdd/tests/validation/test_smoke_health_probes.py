"""Tests for smoke health probes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from open_fdd.validation.smoke_health_probes import (
    _tail_log_errors,
    probe_api_health,
    probe_bacnet_override_scan,
    run_health_battery,
)


def test_tail_log_errors_skips_health_lines(tmp_path: Path):
    log = tmp_path / "bridge.log"
    log.write_text(
        "INFO ok\n127.0.0.1 - GET /api/health HTTP/1.1 200 -\nERROR something broke\n",
        encoding="utf-8",
    )
    hits = _tail_log_errors(log)
    assert len(hits) == 1
    assert "something broke" in hits[0]


@patch("open_fdd.validation.smoke_health_probes._fetch")
def test_probe_api_health_ok(mock_fetch):
    mock_fetch.side_effect = [
        (200, {"ok": True}),
        (200, {"devices": [{"device_instance": "5007"}]}),
        (200, {"poll_interval_s": 60}),
        (200, {"stack": "ok"}),
    ]
    result = probe_api_health(base="http://127.0.0.1:8765", token="tok")
    assert result.ok
    assert result.data["endpoints"]["/api/bench/poll-status"]["device_5007"] is True


@patch("open_fdd.validation.smoke_health_probes._fetch")
def test_probe_bacnet_override_scan_interval(mock_fetch):
    body = {
        "scan_interval_s": 3600,
        "device_count": 3,
        "cursor": 1,
        "operator_priority": 8,
        "full_rotation_hours": 3.0,
        "last_scan_device": 5007,
        "last_scan_at": "2026-06-19T14:00:00+00:00",
        "scan_health": {"ok": True, "status": "healthy", "detail": "ok"},
    }
    mock_fetch.side_effect = [
        (200, body),
        (200, {"site_id": "demo"}),
    ]
    result = probe_bacnet_override_scan(base="http://127.0.0.1:8765", token="tok")
    assert result.ok
    assert result.data["status"]["last_scan_device"] == 5007


@patch("open_fdd.validation.smoke_health_probes._fetch")
def test_probe_bacnet_override_bad_interval(mock_fetch):
    mock_fetch.side_effect = [
        (200, {"scan_interval_s": 300, "device_count": 1, "cursor": 0, "operator_priority": 8}),
        (200, {}),
    ]
    result = probe_bacnet_override_scan(base="http://127.0.0.1:8765", token="tok")
    assert not result.ok


@patch("open_fdd.validation.smoke_health_probes.probe_docker_compose")
@patch("open_fdd.validation.smoke_health_probes.probe_service_logs")
@patch("open_fdd.validation.smoke_health_probes.probe_frontend")
@patch("open_fdd.validation.smoke_health_probes.probe_bacnet_override_scan")
@patch("open_fdd.validation.smoke_health_probes.probe_api_health")
def test_run_health_battery(mock_api, mock_ov, mock_fe, mock_logs, mock_docker, tmp_path: Path):
    from open_fdd.validation.smoke_health_probes import ProbeResult

    mock_api.return_value = ProbeResult(name="api_health", ok=True)
    mock_ov.return_value = ProbeResult(name="bacnet_override_scan", ok=True)
    mock_fe.return_value = ProbeResult(name="frontend", ok=True)
    mock_logs.return_value = ProbeResult(name="service_logs", ok=True)
    mock_docker.return_value = ProbeResult(name="docker", ok=True)

    snap = run_health_battery(base="http://x", token=None, repo_root=tmp_path)
    assert snap["pass"] is True
    assert len(snap["probes"]) == 5
