"""Tests for gateway CLI bind resolution (no uvicorn)."""

from __future__ import annotations

import os

import pytest

from open_fdd.gateway.cli import resolve_gateway_bind


@pytest.fixture
def clean_bridge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OFDD_BRIDGE_URL",
        "OFDD_DESKTOP_BRIDGE_BASE",
        "OFDD_BRIDGE_HOST",
        "OFDD_BRIDGE_PORT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_resolve_defaults(clean_bridge_env: None) -> None:
    h, p = resolve_gateway_bind()
    assert h == "127.0.0.1"
    assert p == 8765


def test_resolve_from_bridge_url(clean_bridge_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://192.168.1.10:9999")
    h, p = resolve_gateway_bind()
    assert h == "192.168.1.10"
    assert p == 9999


def test_resolve_invalid_port_in_url_uses_default(clean_bridge_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://127.0.0.1:70000")
    h, p = resolve_gateway_bind(default_port=8765)
    assert h == "127.0.0.1"
    assert p == 8765


def test_resolve_invalid_env_port_uses_default(clean_bridge_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_PORT", "not-a-port")
    h, p = resolve_gateway_bind()
    assert h == "127.0.0.1"
    assert p == 8765


def test_resolve_env_host_port(clean_bridge_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "0.0.0.0")
    monkeypatch.setenv("OFDD_BRIDGE_PORT", "9000")
    h, p = resolve_gateway_bind()
    assert h == "0.0.0.0"
    assert p == 9000


def test_url_wins_over_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BRIDGE_URL", "http://from-url:1111")
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "ignored-host")
    monkeypatch.setenv("OFDD_BRIDGE_PORT", "2222")
    h, p = resolve_gateway_bind()
    assert h == "from-url"
    assert p == 1111
