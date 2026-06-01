from __future__ import annotations

from bacnet_toolshed.nic_bind import (
    normalize_bacnet_bind,
    resolve_bacnet_bind,
    should_auto_resolve_bind,
)


def test_normalize_bacnet_bind_adds_port():
    assert normalize_bacnet_bind("192.168.204.12/24") == "192.168.204.12/24:47808"
    assert normalize_bacnet_bind("192.168.204.12/24:47808") == "192.168.204.12/24:47808"


def test_should_auto_resolve_loopback():
    assert should_auto_resolve_bind("127.0.0.1/24:47808") is True
    assert should_auto_resolve_bind("0.0.0.0/24:47808") is True
    assert should_auto_resolve_bind("192.168.1.50/24:47808") is False


def test_resolve_bacnet_bind_keeps_explicit_lan(monkeypatch):
    monkeypatch.delenv("OFDD_BACNET_BIND", raising=False)
    assert resolve_bacnet_bind("192.168.50.10/24") == "192.168.50.10/24:47808"


def test_resolve_bacnet_bind_auto_from_loopback(monkeypatch):
    monkeypatch.delenv("OFDD_BACNET_BIND", raising=False)
    monkeypatch.setenv("OFDD_BACNET_BIND_STRICT", "0")

    def fake_detect():
        return ("192.168.204.12", 24)

    monkeypatch.setattr("bacnet_toolshed.nic_bind.detect_lan_ipv4", fake_detect)
    assert resolve_bacnet_bind("127.0.0.1/24:47808") == "192.168.204.12/24:47808"
