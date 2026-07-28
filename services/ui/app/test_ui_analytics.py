"""Milestone C — ui_analytics payload builders (mocked central; no Streamlit required)."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

# ui_rcx_tab / streamlit imports are not required here; keep streamlit mock for safety
# if transitive imports pull it in.
sys.modules.setdefault("streamlit", MagicMock())

from app import central_client, ui_analytics  # noqa: E402


def _fan_frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "fan_status": [1, 1, 0, 0],
            "return_air_temp": [70.0, 70.0, 70.0, 70.0],
            "mixed_air_temp": [55.0, 55.0, 55.0, 55.0],
            "outside_air_temp": [40.0, 40.0, 40.0, 40.0],
            "outside_air_damper": [50.0, 50.0, 50.0, 50.0],
            "discharge_air_temp": [55.0, 55.0, 55.0, 55.0],
        },
        index=idx,
    )


def test_build_runtime_samples_prefers_fan_status() -> None:
    frames = {"AHU-1": _fan_frame()}
    role_map = {
        "AHU-1": {
            "fan-status": "fan_status",
            "fan-cmd": "fan_status",  # same col; status path wins by role order
        }
    }
    samples = ui_analytics.build_runtime_samples(frames, role_map)
    assert len(samples) == 4
    assert samples[0]["equipment_id"] == "AHU-1"
    assert samples[0]["on"] is True
    assert samples[2]["on"] is False
    assert "T" in samples[0]["timestamp"] or "Z" in samples[0]["timestamp"]


def test_build_runtime_samples_fan_cmd_fallback() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="5min", tz="UTC")
    frames = {
        "AHU-2": pd.DataFrame({"sf_cmd": [100.0, 0.0]}, index=idx),
    }
    role_map = {"AHU-2": {"fan-cmd": "sf_cmd"}}
    samples = ui_analytics.build_runtime_samples(frames, role_map)
    assert len(samples) == 2
    assert samples[0]["on"] is True
    assert samples[1]["on"] is False


def test_fetch_runtime_analytics_skips_when_unhealthy() -> None:
    with patch.object(central_client, "health_ok", return_value=False):
        out = ui_analytics.fetch_runtime_analytics({"AHU-1": _fan_frame()}, {})
    assert out.get("ok") is False
    assert out.get("central_down") is True


def test_fetch_runtime_analytics_posts_samples() -> None:
    frames = {"AHU-1": _fan_frame()}
    role_map = {"AHU-1": {"fan-status": "fan_status"}}
    fake = {
        "ok": True,
        "analytics": {
            "engine": "central-analytics-v1",
            "query_version": "runtime-v1",
            "run_id": "run-1",
            "rows": [{"equipment_id": "AHU-1", "run_hours": 0.17}],
        },
    }
    with patch.object(central_client, "health_ok", return_value=True):
        with patch.object(central_client, "analytics_post", return_value=fake) as post:
            out = ui_analytics.fetch_runtime_analytics(frames, role_map)
    assert out.get("ok") is True
    assert out["analytics"]["rows"][0]["equipment_id"] == "AHU-1"
    args, kwargs = post.call_args
    assert args[0] == "runtime"
    payload = args[1]
    assert "samples" in payload
    assert len(payload["samples"]) == 4
    assert payload["query_version"] == "runtime-v1"


def test_fetch_runtime_surfaces_central_error_no_fallback() -> None:
    frames = {"AHU-1": _fan_frame()}
    role_map = {"AHU-1": {"fan-status": "fan_status"}}
    with patch.object(central_client, "health_ok", return_value=True):
        with patch.object(
            central_client,
            "analytics_post",
            return_value={"ok": False, "error": "boom", "central_down": True},
        ):
            out = ui_analytics.fetch_runtime_analytics(frames, role_map)
    assert out.get("ok") is False
    assert out.get("error") == "boom"
    assert "analytics" not in out or out.get("analytics") is None


def test_build_economizer_series_points() -> None:
    frames = {"AHU-1": _fan_frame()}
    role_map = {
        "AHU-1": {
            "fan-status": "fan_status",
            "return-air-temp": "return_air_temp",
            "mixed-air-temp": "mixed_air_temp",
            "outside-air-temp": "outside_air_temp",
            "outside-air-damper": "outside_air_damper",
            "discharge-air-temp": "discharge_air_temp",
            "equipment_type": "AHU",
        }
    }
    series = ui_analytics.build_economizer_series(frames, role_map)
    pts = series["points"]
    assert len(pts) == 4
    assert pts[0]["equipment_id"] == "AHU-1"
    assert pts[0]["oat_f"] == 40.0
    assert pts[0]["rat_f"] == 70.0
    assert pts[0]["mat_f"] == 55.0
    assert pts[0]["fan_on"] is True
    assert "oa_damper_pct" in pts[0]


def test_provenance_caption() -> None:
    cap = ui_analytics.provenance_caption(
        {
            "engine": "central-analytics-v1",
            "query_version": "runtime-v1",
            "run_id": "run-abc",
        }
    )
    assert "central-analytics-v1" in cap
    assert "runtime-v1" in cap
    assert "run-abc" in cap


def test_oracle_fallback_enabled_reads_env() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENFDD_ANALYTICS_ORACLE", None)
        assert ui_analytics.oracle_fallback_enabled() is False
    with patch.dict(os.environ, {"OPENFDD_ANALYTICS_ORACLE": "1"}):
        assert ui_analytics.oracle_fallback_enabled() is True


def test_analytics_post_rejects_unknown_family() -> None:
    out = central_client.analytics_post("not-a-family", {})
    assert out.get("ok") is False
    assert "unknown" in (out.get("error") or "").lower()


def test_analytics_post_posts_to_path() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b'{"ok": true, "analytics": {}}'
    fake_resp.json.return_value = {"ok": True, "analytics": {}}
    with patch.object(central_client, "_request", return_value=fake_resp) as req:
        out = central_client.analytics_post("runtime", {"samples": []})
    assert out.get("ok") is True
    assert "/api/analytics/runtime" in req.call_args[0][1]
