"""acme_patch_oat_column — API-first path when --host and --token are set."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "acme_patch_oat_column.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("acme_patch_oat_column", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_api_path_patches_and_imports(monkeypatch):
    mod = _load_module()
    model = {"points": [{"id": "1100-unknown-2", "external_id": "", "fdd_input": ""}]}
    calls: list[str] = []

    def fake_fetch(base, token):
        calls.append(f"fetch:{base}")
        return json.loads(json.dumps(model))

    def fake_push(base, token, payload):
        calls.append(f"push:{base}")
        assert payload["points"][0]["external_id"] == "oa-t"

    monkeypatch.setattr(mod, "_fetch_model", fake_fetch)
    monkeypatch.setattr(mod, "_push_model", fake_push)
    monkeypatch.setattr(
        sys,
        "argv",
        ["acme_patch_oat_column.py", "--host", "100.1.2.3", "--token", "tok"],
    )
    assert mod.main() == 0
    assert calls == ["fetch:http://100.1.2.3", "push:http://100.1.2.3"]


def test_api_path_no_change_skips_import(monkeypatch):
    mod = _load_module()
    model = {"points": [{"id": "1100-unknown-2", "external_id": "oa-t", "fdd_input": "oa-t"}]}
    pushed = []

    monkeypatch.setattr(mod, "_fetch_model", lambda *_: model)
    monkeypatch.setattr(mod, "_push_model", lambda *_a, **_k: pushed.append(1))
    monkeypatch.setattr(
        sys,
        "argv",
        ["acme_patch_oat_column.py", "--host", "edge", "--token", "t"],
    )
    assert mod.main() == 0
    assert pushed == []
