"""http_probes must survive slow agent endpoints and still run BACnet checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "infra" / "ansible" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import http_probes  # noqa: E402


def test_fetch_timeout_becomes_runtime_error():
    with patch("urllib.request.urlopen", side_effect=TimeoutError):
        with pytest.raises(RuntimeError, match="timed out"):
            http_probes.fetch("http://127.0.0.1:9/nope", timeout=1.0)


def test_check_agent_stack_context_timeout_is_structured():
    def fake_fetch(url, *, timeout=20.0, headers=None):
        if "context" in url:
            raise RuntimeError("request timed out after 1s")
        return 200, "{}", {}

    with patch.object(http_probes, "fetch", side_effect=fake_fetch):
        out = http_probes.check_agent_stack("http://edge", "token", require_ollama=False)
    assert out["errors"]
    assert "context" in out["errors"][0]


def test_main_continues_bacnet_when_agent_context_times_out():
    login_ok = {"token": "t", "errors": [], "login_status": 200}
    bacnet_ok = {
        "errors": [],
        "warnings": [],
        "bacnet_tree_status": 200,
        "bacnet_device_count": 2,
        "bacnet_enabled_points": 10,
    }

    def fake_agent(*_a, **_k):
        raise RuntimeError("request timed out after 1s")

    argv = ["http_probes.py", "check", "http://edge", "u", "p", "--site-id", "acme"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(http_probes, "check_login", return_value=login_ok),
        patch.object(http_probes, "check_entry", return_value={"errors": [], "warnings": []}),
        patch.object(http_probes, "check_model_api", return_value={"errors": [], "warnings": [], "active_site_id": "acme"}),
        patch.object(http_probes, "check_agent_stack", side_effect=fake_agent),
        patch.object(http_probes, "check_integrator_ui_api", return_value={"errors": [], "warnings": []}),
        patch.object(http_probes, "check_bacnet_driver", return_value=bacnet_ok),
        patch.object(http_probes, "check_agent_chat", return_value={"errors": [], "warnings": [], "skipped": True}),
    ):
        rc = http_probes.main()
    assert rc == 1
    # BACnet ran — errors should include agent failure, not a bare traceback exit
