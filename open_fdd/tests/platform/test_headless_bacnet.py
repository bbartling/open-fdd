from __future__ import annotations

from unittest.mock import patch

import pytest

from open_fdd.platform.drivers import headless_bacnet as hb


def test_post_json_success() -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return b'{"success":true,"rows":1}'

    with patch.object(hb.urllib.request, "urlopen", return_value=_Resp()):
        out = hb._post_json("http://example/ingest/bacnet", {"site_id": "s1"})
    assert out.get("success") is True


def test_main_once_bridge_mode_exits_on_missing_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BACNET_SITE_ID", "")
    with pytest.raises(SystemExit) as ei:
        hb.main(["once", "--mode", "bridge", "--site-id", ""])
    assert ei.value.code == 2


def test_main_once_local_requires_server(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as ei:
        hb.main(["once", "--mode", "local", "--site-id", "abc", "--server-url", ""])
    assert ei.value.code == 2


def test_main_once_local_calls_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)
        return {"success": True, "rows": 3}

    monkeypatch.setattr(hb, "_run_local_once", _fake)
    hb.main(["once", "--mode", "local", "--site-id", "site-1", "--server-url", "http://diy:8080"])
    assert calls == [
        {"site_id": "site-1", "server_url": "http://diy:8080", "api_key": ""},
    ]
