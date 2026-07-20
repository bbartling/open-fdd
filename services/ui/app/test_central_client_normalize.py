"""Unit tests for UI → SQL param normalization (no central required)."""

from __future__ import annotations

from app.central_client import normalize_params_payload, normalize_rule_params


def test_confirm_min_becomes_confirm_seconds() -> None:
    out = normalize_rule_params("FC1", {"confirm_min": 120.0, "eps_dsp": 0.12})
    assert out["confirm_seconds"] == 7200.0
    assert "confirm_min" not in out
    assert out["eps_dsp"] == 0.12


def test_confirm_seconds_wins_over_confirm_min() -> None:
    out = normalize_rule_params(
        "FC1", {"confirm_min": 120.0, "confirm_seconds": 60.0}
    )
    assert out["confirm_seconds"] == 60.0


def test_vav_zone_aliases() -> None:
    out = normalize_rule_params("VAV-1", {"zone_lo": 68.0, "zone_hi": 76.0})
    assert out["zone_t_lo"] == 68.0
    assert out["zone_t_hi"] == 76.0
    assert "zone_lo" not in out


def test_fc1_fan_hi_to_eps_vfd() -> None:
    out = normalize_rule_params("FC1", {"fan_hi": 0.87})
    assert abs(out["eps_vfd_spd"] - 0.13) < 1e-9
    assert "fan_hi" not in out


def test_payload_normalize() -> None:
    payload = normalize_params_payload(
        {"FC1": {"confirm_min": 5.0}, "VAV-1": {"zone_lo": 70.0}}
    )
    assert payload is not None
    assert payload["FC1"]["confirm_seconds"] == 300.0
    assert payload["VAV-1"]["zone_t_lo"] == 70.0
