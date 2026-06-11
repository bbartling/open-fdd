"""Edge ops patch — FDD presets, export-all, pooge, BACnet bind, cloud exporter."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

def test_fdd_query_presets_list(client):
    res = client.get("/api/model/fdd-query-presets")
    assert res.status_code == 200
    presets = res.json()["presets"]
    assert any(p["preset_id"] == "rules_to_sensors" for p in presets)


def test_fdd_query_preset_empty_model(client):
    res = client.get("/api/model/fdd-query-presets/missing_rule_bindings")
    assert res.status_code == 200
    body = res.json()
    assert body["query_type"] == "composed"
    assert "columns" in body
    assert isinstance(body["rows"], list)


def test_pooge_preview_dry_run(client):
    res = client.post(
        "/api/host/pooge/preview",
        json={"dry_run": True, "clear_historian": True, "clear_bacnet": True},
    )
    assert res.status_code == 200
    assert res.json().get("dry_run") is True
    assert "targets" in res.json()


def test_pooge_run_wrong_confirmation(client):
    res = client.post(
        "/api/host/pooge/run",
        json={"dry_run": False, "confirmation": "nope", "clear_exports": True},
    )
    assert res.status_code == 200
    assert res.json().get("ok") is False


def test_bacnet_interfaces(client, monkeypatch):
    monkeypatch.setattr(
        "bacnet_toolshed.nic_bind.list_host_interfaces",
        lambda: [{"interface": "eth0", "ipv4": "192.168.1.10", "prefix_len": "24", "label": "eth0 — 192.168.1.10", "kind": "lan"}],
    )
    monkeypatch.setattr("openfdd_bridge.bacnet_bind_config.read_bacnet_bind", lambda: "192.168.1.10/24:47808")
    res = client.get("/api/bacnet/interfaces")
    assert res.status_code == 200
    assert res.json()["interfaces"]


def test_bacnet_bind_address(client, tmp_path, monkeypatch):
    env = tmp_path / "bacnet" / "commissioning" / "commission.env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("BACNET_BIND=127.0.0.1/24:47808\n", encoding="utf-8")
    monkeypatch.setattr("openfdd_bridge.bacnet_bind_config.commission_env_path", lambda: env)
    monkeypatch.setattr(
        "openfdd_bridge.bacnet_bind_config.restart_bacnet_commission",
        lambda: {"ok": True, "method": "mock"},
    )
    res = client.post(
        "/api/bacnet/bind-address",
        json={"bind": "192.168.1.20/24:47808", "restart": True},
    )
    assert res.status_code == 200
    assert "192.168.1.20" in env.read_text(encoding="utf-8")


def test_export_all_rules_zip(client, monkeypatch):
    from openfdd_bridge.rule_kit import RuleKitError

    def fake_build(**kwargs):
        rule_id = kwargs.get("rule_id") or "r1"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("kit_meta.json", json.dumps({"row_count": 1, "data_source": "test"}))
            zf.writestr("rule.py", "x = 1\n")
        return buf.getvalue(), f"{rule_id}.zip"

    monkeypatch.setattr("openfdd_bridge.rule_kit.build_rule_kit_zip", fake_build)
    monkeypatch.setattr(
        "openfdd_bridge.rule_kit.RuleStore.list_rules",
        lambda self: [{"id": "r1", "name": "Rule 1", "enabled": True}, {"id": "r2", "name": "Rule 2", "enabled": False}],
    )

    res = client.get("/api/rules/export-all-kit")
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert "manifest.json" in zf.namelist()
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["success_count"] >= 1
    assert manifest["skipped_count"] >= 1


def test_cloud_exporter_dry_run(monkeypatch):
    import sys

    ws = Path(__file__).resolve().parents[2] / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    from cloud_exporter.client import build_payload, post_payload
    from cloud_exporter.config import ExporterConfig

    class FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True}

    class FakeClient:
        def get(self, url, **kwargs):
            return FakeResp()

        def post(self, url, **kwargs):
            return FakeResp()

    cfg = ExporterConfig(
        bridge_base_url="http://test",
        export_endpoint="https://example.com/hook",
        interval_seconds=300,
        dry_run=True,
        token="secret",
        site_id="demo",
        include_readings=True,
        include_faults=False,
        include_model_summary=False,
        max_points=10,
        timeout_seconds=5,
    )
    payload = build_payload(FakeClient(), cfg)
    assert payload["source"] == "open-fdd"
    result = post_payload(FakeClient(), cfg, payload)
    assert result.get("dry_run") is True
