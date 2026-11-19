"""open-fdd-ml detect publishes assessed vs unassessed rows (#1666): missing inputs are never counted healthy."""
from __future__ import annotations

import json

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from open_fdd.ml.cli import main  # noqa: E402

DAY = 288


def _ahu(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    oat = 10 + 12 * np.sin(np.arange(n) / DAY * 2 * np.pi) + rng.normal(0, 0.3, n)
    rat = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    mat = damper * oat + (1 - damper) * rat + rng.normal(0, 0.1, n)
    valve = np.clip((mat - 13) / 10, 0, 1)
    sat = mat - 10 * valve + rng.normal(0, 0.1, n)
    return pd.DataFrame({
        "discharge-air-temp": sat, "discharge-air-temp-sp": 13.0, "mixed-air-temp": mat, "return-air-temp": rat,
        "outside-air-temp": oat, "outside-air-damper": damper, "cooling-valve": valve, "fan-cmd": 0.7 + 0.1 * valve,
        "fan-status": 1.0, "occupied": 1.0,
    }, index=idx)


def _folder(tmp_path, frame, name="AHU_1"):
    folder = tmp_path / name
    folder.mkdir()
    frame.to_csv(folder / "history_wide.csv", index_label="timestamp_utc")
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": {c: c for c in frame.columns}}),
                                            encoding="utf-8")
    return folder


@pytest.mark.parametrize("method", ["pca", "grey_box"])
def test_complete_inputs_are_all_assessed(tmp_path, capsys, method):
    folder = _folder(tmp_path, _ahu(6 * DAY))
    out = tmp_path / "out"
    assert main(["detect", str(folder), "--method", method, "--train-until", "2026-01-08", "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["assessed_rows"] + s["unassessed_rows"] == s["active_rows"]
    assert s["assessed_coverage"] is not None and s["assessed_coverage"] > 0.5
    flags = pd.read_csv(out / "flags.csv")
    assert set(flags["assessment"].dropna()) <= {"assessed", "inactive", "missing_inputs", "no_residual"}
    capsys.readouterr()


@pytest.mark.parametrize("method", ["pca", "grey_box"])
def test_missing_inputs_are_unassessed_not_healthy(tmp_path, capsys, method):
    frame = _ahu(6 * DAY)
    later = frame.index >= pd.Timestamp("2026-01-08", tz="UTC")
    frame.loc[later, ["mixed-air-temp", "discharge-air-temp"]] = np.nan  # sensors drop out after the cutoff
    folder = _folder(tmp_path, frame)
    out = tmp_path / "out"
    assert main(["detect", str(folder), "--method", method, "--train-until", "2026-01-08", "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["active_rows"] > 0 and s["flagged_rows"] == 0
    assert s["unassessed_rows"] > 0 and s["assessed_coverage"] < 0.5  # quiet because unassessed, and it says so
    assert set(s["unassessed_reasons"]) <= {"missing_inputs", "no_residual"}
    capsys.readouterr()


def test_methods_without_assessment_say_so(tmp_path, capsys):
    folder = _folder(tmp_path, _ahu(3 * DAY))
    out = tmp_path / "out"
    assert main(["detect", str(folder), "--method", "zscore", "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["assessed_rows"] is None and "assessment_note" in s
    assert "assessment" not in pd.read_csv(out / "flags.csv").columns
    capsys.readouterr()
