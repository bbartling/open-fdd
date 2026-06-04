import pytest

from bacnet_toolshed.device_identity import (
    DEFAULT_BACNET_DEVICE_NAME,
    apply_device_identity_defaults,
    device_name_from_cfg,
    instance_id_from_cfg,
    normalize_bacnet_device_name,
)


def test_default_device_name():
    assert normalize_bacnet_device_name("") == DEFAULT_BACNET_DEVICE_NAME
    assert normalize_bacnet_device_name(None) == "OpenFDD"


def test_instance_clamp():
    assert instance_id_from_cfg({"BACNET_INSTANCE": "3456791"}) == 3456791
    assert instance_id_from_cfg({"BACNET_INSTANCE": "999999999"}) == 4194302


def test_apply_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_BACNET_DEVICE_NAME", raising=False)
    monkeypatch.delenv("OFDD_BACNET_INSTANCE", raising=False)
    cfg = apply_device_identity_defaults({})
    assert cfg["BACNET_NAME"] == "OpenFDD"
    assert cfg["BACNET_INSTANCE"] == "599999"


def test_custom_name_preserved():
    assert device_name_from_cfg({"BACNET_NAME": "Site-Head-End"}) == "Site-Head-End"


def test_env_overrides_cfg(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_BACNET_DEVICE_NAME", "Env-Override")
    monkeypatch.setenv("OFDD_BACNET_INSTANCE", "1234")
    assert device_name_from_cfg({"BACNET_NAME": "From-Cfg"}) == "Env-Override"
    assert instance_id_from_cfg({"BACNET_INSTANCE": "999999999"}) == 1234
