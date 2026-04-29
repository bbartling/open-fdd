from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.platform.drivers.bacnet_driver import run_bacnet_scrape


class _MemStore:
    def __init__(self) -> None:
        self.frames: list[tuple[str, str, pd.DataFrame]] = []

    def write_frame(self, *, source: str, site_id: str, frame: pd.DataFrame) -> str:
        self.frames.append((source, site_id, frame))
        return "mem"


def _minimal_model(site_id: str, *, polling) -> dict:
    return {
        "points": [
            {
                "site_id": site_id,
                "external_id": "sat",
                "bacnet_device_id": "123",
                "object_identifier": "analog-input,1",
                "polling": polling,
            }
        ]
    }


def test_bacnet_skips_string_false_polling() -> None:
    store = _MemStore()
    out = run_bacnet_scrape(
        store=store,
        model=_minimal_model("s1", polling="false"),
        site_id="s1",
        server_url="http://example.com:8080",
    )
    assert out.success is False
    assert "polling=true" in (out.error or "").lower()
    assert store.frames == []


def test_bacnet_includes_string_true_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def _fake_urlopen(req, timeout=25):  # noqa: ARG001
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b'{"result":{"data":{"results":[{"value":72.0}]}}}'

        return _Resp()

    monkeypatch.setattr("open_fdd.platform.drivers.bacnet_driver.urllib.request.urlopen", _fake_urlopen)
    store = _MemStore()
    out = run_bacnet_scrape(
        store=store,
        model=_minimal_model("s1", polling="true"),
        site_id="s1",
        server_url="http://example.com:8080",
    )
    assert out.success is True
    assert len(store.frames) == 1
