"""Offline tests for RCx overnight patch-cycle helpers."""

from __future__ import annotations

from scripts.rcx_central_overnight_patch_cycle import _env_bool, _env_int, _http_json


def test_env_int_default():
    assert _env_int("RCX_PATCH_CYCLES_MISSING", 3) == 3


def test_env_bool_false():
    assert _env_bool("OPENFDD_LIVE_ACME") is False


def test_http_json_local_missing():
    code, data, err = _http_json("http://127.0.0.1:1/", timeout=1.0)
    assert code == 0
    assert data is None
    assert err
