"""Tests for BAS-style latched dashboard alarms."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge import fault_alarm_latch  # noqa: E402


@pytest.fixture()
def latch_file(tmp_path, monkeypatch):
    path = tmp_path / "fault_alarm_latch.json"
    monkeypatch.setattr(fault_alarm_latch, "fault_alarm_latch_path", lambda: path)
    return path


def _alert(aid: str, title: str = "Test fault") -> dict:
    return {"id": aid, "title": title, "severity": "warning", "source": "fdd"}


def test_latch_keeps_alarm_after_live_clears(latch_file):
    live = [_alert("fdd-1")]
    active = fault_alarm_latch.apply_alarm_latch(live)
    assert len(active) == 1

    active = fault_alarm_latch.apply_alarm_latch([])
    assert len(active) == 1
    assert active[0]["id"] == "fdd-1"


def test_clear_removes_from_active(latch_file):
    fault_alarm_latch.apply_alarm_latch([_alert("fdd-1")])
    fault_alarm_latch.clear_alarms(["fdd-1"], cleared_by="tech")
    active = fault_alarm_latch.apply_alarm_latch([])
    assert active == []


def test_re_alarm_after_clear_when_live_returns(latch_file):
    fault_alarm_latch.apply_alarm_latch([_alert("fdd-1")])
    fault_alarm_latch.clear_alarms(["fdd-1"], cleared_by="tech")
    active = fault_alarm_latch.apply_alarm_latch([_alert("fdd-1", "Still bad")])
    assert len(active) == 1
    assert active[0]["title"] == "Still bad"
    doc = json.loads(latch_file.read_text())
    assert "cleared_at" not in doc["alarms"]["fdd-1"]
