"""``open-fdd-nf export-folder`` against the mock NF (nf-app/dev/mock-nf.mjs) (#1653)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.nf import NFClient  # noqa: E402
from open_fdd.nf import cli as nfcli  # noqa: E402
from open_fdd.nf.model import equipment_frames, load_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
FROZEN_NOW = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def mock_url():
    if not NODE:
        pytest.skip("node is required for the mock NF")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "MOCK_NOW": FROZEN_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
    proc = subprocess.Popen([NODE, str(ROOT / "nf-app" / "dev" / "mock-nf.mjs"), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/v1/platform/info", timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("mock NF did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch):
    from open_fdd.nf.model import default_range as _default_range
    monkeypatch.setattr("open_fdd.nf.model.default_range",
                        lambda days, now=None: _default_range(days, now=now or FROZEN_NOW))


def run(capsys, *argv):
    code = nfcli.main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_export_folder_is_si_and_feeds_the_offline_tools(mock_url, tmp_path, capsys):
    out = tmp_path / "AHU_1"
    code, so, _ = run(capsys, "export-folder", "--url", mock_url, "--equip", "AHU-1", "--days", "2", "--out", str(out))
    assert code == 0 and "SI" in so
    cmap = json.loads((out / "column_map.json").read_text(encoding="utf-8"))
    assert cmap["equipType"] == "AHU" and cmap["site_id"] == "site-north" and cmap["equipment_id"] == "AHU-1"
    assert cmap["units"]["discharge-air-temp"] == "°C" and cmap["units"]["duct-static-pressure"] == "Pa"
    assert cmap["bindings"]["discharge-air-temp"]["source_unit"] == "°F"
    assert cmap["units"]["outside-air-damper"] == "fraction"
    assert cmap["skipped"] == {} and cmap["unit_unverified"] == {} and isinstance(cmap["unmapped_points"], list)

    # values equal the SI frames the rules use
    client = NFClient(mock_url)
    ref = equipment_frames(client, load_model(client), FROZEN_NOW - timedelta(days=2), FROZEN_NOW,
                           equip="AHU-1")[("site-north", "AHU-1")]
    from open_fdd.analytics.anomaly.io import load_device_folder

    dev = load_device_folder(out)  # default ahu_only=True: the AHU stamp is honoured
    assert ("discharge-air-temp", "discharge-air-temp") in dev.points and not dev.missing
    got = dev.frame["discharge-air-temp"]
    assert len(got) == len(ref)
    assert abs(got.to_numpy() - ref["discharge-air-temp"].to_numpy()).max() < 1e-9
    assert dev.frame["outside-air-damper"].between(0, 1).all()


def test_unconvertible_unit_fails_loudly_unless_allowed(mock_url, tmp_path, capsys):
    out = tmp_path / "CT_1"
    code, _, err = run(capsys, "export-folder", "--url", mock_url, "--equip", "CT-1", "--days", "1", "--out", str(out))
    assert code == 2 and "cannot be converted" in err and "--allow-skips" in err
    assert not out.exists()  # nothing written
    code, _, err = run(capsys, "export-folder", "--url", mock_url, "--equip", "CT-1", "--days", "1", "--out", str(out),
                       "--allow-skips")
    cmap = json.loads((out / "column_map.json").read_text(encoding="utf-8"))
    assert code == 0 and "tower_fan_cmd" in cmap["skipped"] and "no unit" in cmap["skipped"]["tower_fan_cmd"]
    assert "skipped: tower_fan_cmd" in err


def test_needs_one_equipment(mock_url, tmp_path, capsys):
    code, _, err = run(capsys, "export-folder", "--url", mock_url, "--days", "1", "--out", str(tmp_path / "x"))
    assert code == 2 and "--equip" in err
    code, _, err = run(capsys, "export-folder", "--url", mock_url, "--equip", "NOPE-9", "--days", "1",
                       "--out", str(tmp_path / "x"))
    assert code == 2 and "no equipment matches" in err
    code, _, err = run(capsys, "export-folder", "--url", mock_url, "--equip", "AHU-1", "--site", "site-south",
                       "--days", "1", "--out", str(tmp_path / "x"))
    assert code == 2 and "site-south" in err


def test_ambiguous_equipment_names_the_choices():
    from open_fdd.nf.client import NFError
    from open_fdd.nf.device_folder import resolve_equipment
    from open_fdd.nf.model import Model

    equips = [{"name": "AHU-1", "attrs": {"id": "AHU-1", "siteRef": s, "ahu": "m:"}} for s in ("a", "b")]
    model = Model(sites=[{"attrs": {"id": "a"}}, {"attrs": {"id": "b"}}], equips=equips, points=[], devices=[])
    with pytest.raises(NFError, match="add --site"):
        resolve_equipment(model, "AHU-1")
