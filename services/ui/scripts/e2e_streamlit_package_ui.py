#!/usr/bin/env python3
"""E2E: Streamlit AppTest drives the real zip picker + Load + Run + Results.

Fixtures (optional real zips) come only from ``VIBE19_TEST_PACKAGE_DIR`` or the
test helper's local fallback — never hardcoded in ``app/``.

Usage:
  python scripts/e2e_streamlit_package_ui.py
  pytest tests/test_e2e_streamlit_package_ui.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ss(at, key, default=None):
    try:
        return at.session_state[key]
    except Exception:
        return default


def _building_zip_uploader(at):
    for fu in at.sidebar.file_uploader:
        if (fu.label or "") == "Building package zip(s)":
            return fu
    raise AssertionError("Building package zip(s) uploader missing")


def _load_zip_button(at):
    for b in at.sidebar.button:
        if (b.label or "") == "Load zip(s)":
            return b
    raise AssertionError("Load zip(s) button missing")


def _set_radio_option(at, option: str) -> bool:
    for r in at.radio:
        opts = list(getattr(r, "options", []) or [])
        if option in opts:
            r.set_value(option)
            return True
    return False


def _click_labeled_button(at, label: str, key: str | None = None) -> None:
    for b in at.button:
        if (b.label or "") != label:
            continue
        if key is not None and getattr(b, "key", None) not in (None, key):
            continue
        b.click()
        return
    raise AssertionError(f"button {label!r} missing")


def cloud_app(monkeypatch=None):
    import pytest

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    if monkeypatch is not None:
        monkeypatch.setenv("APP_MODE", "cloud")
        monkeypatch.delenv("VIBE19_BOOTSTRAP", raising=False)
    else:
        os.environ["APP_MODE"] = "cloud"
        os.environ.pop("VIBE19_BOOTSTRAP", None)

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=300)
    at.run()
    assert not at.exception, f"startup: {list(at.exception)}"
    return at


def resolve_fixture_zips(*, prefer_real: bool) -> tuple[str, bytes, str | None, bytes | None, bool]:
    """Return (building_name, building_bytes, weather_name, weather_bytes, is_real)."""
    from tests.test_upload_building_weather_combos import (
        _building_zip_with_nested_weather,
        _optional_real_package_dir,
        _weather_only_zip,
    )

    if prefer_real:
        real_dir = _optional_real_package_dir()
        if real_dir is not None:
            bz = real_dir / "BUILDING_100.zip"
            wz = real_dir / "weather.zip"
            if bz.is_file():
                return (
                    bz.name,
                    bz.read_bytes(),
                    wz.name if wz.is_file() else None,
                    wz.read_bytes() if wz.is_file() else None,
                    True,
                )
    return ("SITE_A.zip", _building_zip_with_nested_weather(), "weather.zip", _weather_only_zip(), False)


def run_upload_variants(*, prefer_real: bool = True, monkeypatch=None) -> dict:
    """Exercise upload combos. Returns summary including ``at`` for a successful load."""
    b_name, b_bytes, w_name, w_bytes, is_real = resolve_fixture_zips(prefer_real=prefer_real)
    summary: dict = {"variants": [], "real": is_real}

    # 1) building alone
    at = cloud_app(monkeypatch)
    _building_zip_uploader(at).set_value((b_name, b_bytes, "application/zip"))
    at.run()
    _load_zip_button(at).click().run()
    assert not at.exception, f"building alone: {list(at.exception)}"
    assert _ss(at, "equipment_frames") or {}, "building alone must load equipment"
    summary["variants"].append("building_alone")
    loaded_at = at

    # 2) weather alone (expect reject)
    if w_bytes is not None and w_name:
        at_w = cloud_app(monkeypatch)
        _building_zip_uploader(at_w).set_value((w_name, w_bytes, "application/zip"))
        at_w.run()
        _load_zip_button(at_w).click().run()
        assert not at_w.exception, f"weather alone uncaught: {list(at_w.exception)}"
        errors = [str(getattr(e, "value", e)) for e in at_w.sidebar.error]
        assert errors, "expected sidebar error for weather-only zip"
        assert not (_ss(at_w, "equipment_frames") or {}), "weather-only must not load"
        summary["variants"].append("weather_alone_reject")

        # 3) building + weather
        at_both = cloud_app(monkeypatch)
        _building_zip_uploader(at_both).set_value(
            [
                (b_name, b_bytes, "application/zip"),
                (w_name, w_bytes, "application/zip"),
            ]
        )
        at_both.run()
        _load_zip_button(at_both).click().run()
        assert not at_both.exception, f"both zips: {list(at_both.exception)}"
        assert _ss(at_both, "equipment_frames") or {}, "building+weather must load"
        summary["variants"].append("building_plus_weather")
        loaded_at = at_both

    # 4) duplicate building select (dedupe, still loads)
    at_dup = cloud_app(monkeypatch)
    _building_zip_uploader(at_dup).set_value(
        [
            (b_name, b_bytes, "application/zip"),
            (b_name, b_bytes, "application/zip"),
        ]
    )
    at_dup.run()
    _load_zip_button(at_dup).click().run()
    assert not at_dup.exception, f"duplicate: {list(at_dup.exception)}"
    assert _ss(at_dup, "equipment_frames") or {}, "duplicate building must still load"
    warn_blob = " ".join(str(getattr(w, "value", w)) for w in at_dup.sidebar.warning).lower()
    # Dedup warning is nice-to-have when multi-upload path emits it
    if "dup" in warn_blob or "duplicate" in warn_blob or "already" in warn_blob:
        summary["variants"].append("duplicate_building_warned")
    else:
        summary["variants"].append("duplicate_building")

    summary["at"] = loaded_at
    return summary


def run_rules_and_results(at) -> None:
    """Open Run Rules → Run (selected equipment) → Results by Category; assert no crash."""
    assert _set_radio_option(at, "Run Rules"), "Run Rules section missing"
    at.run()
    assert not at.exception, f"Run Rules section: {list(at.exception)}"

    _set_radio_option(at, "selected equipment")
    at.run()

    _click_labeled_button(at, "Run", key="run_btn")
    at.run(timeout=300)
    assert not at.exception, f"after Run: {list(at.exception)}"
    results = _ss(at, "batch_results") or []
    assert results, "expected batch_results after Run"

    assert _set_radio_option(at, "Results by Category"), "Results by Category missing"
    at.run()
    assert not at.exception, f"Results by Category: {list(at.exception)}"

    # Overview weather hist path should not crash (empty OK)
    assert _set_radio_option(at, "Overview"), "Overview missing"
    at.run()
    assert not at.exception, f"Overview: {list(at.exception)}"

    assert _set_radio_option(at, "Metering"), "Metering section missing"
    at.run()
    assert not at.exception, f"Metering: {list(at.exception)}"


def main() -> int:
    summary = run_upload_variants(prefer_real=True, monkeypatch=None)
    run_rules_and_results(summary["at"])
    print("OK e2e variants:", ", ".join(summary["variants"]), "real=", summary["real"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
