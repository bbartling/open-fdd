"""SQL fault episode review against ML evidence (#1667, first slice): open_fdd.ml.review."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from open_fdd.ml.review import main, review_episode  # noqa: E402

DAY = 288  # 5-minute rows


def _ahu(n: int, seed: int = 0, damper_stuck: float | None = None) -> pd.DataFrame:
    """Seeded AHU frame obeying the mixed-air balance and a simple coil model (SI, roles)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    oat = 10 + 12 * np.sin(np.arange(n) / DAY * 2 * np.pi) + rng.normal(0, 0.3, n)
    rat = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    actual = damper if damper_stuck is None else np.full(n, damper_stuck)
    mat = actual * oat + (1 - actual) * rat + rng.normal(0, 0.1, n)
    valve = np.clip((mat - 13) / 10, 0, 1)
    sat = mat - 10 * valve + rng.normal(0, 0.1, n)
    return pd.DataFrame({
        "discharge-air-temp": sat, "discharge-air-temp-sp": 13.0, "mixed-air-temp": mat, "return-air-temp": rat,
        "outside-air-temp": oat, "outside-air-damper": damper, "cooling-valve": valve, "fan-cmd": 0.7 + 0.1 * valve,
        "fan-status": 1.0, "occupied": 1.0,
    }, index=idx)


def _history() -> pd.DataFrame:
    """Ten days: healthy for 7, then the damper sticks at minimum (the 'SQL fault')."""
    healthy, stuck = _ahu(10 * DAY, seed=0), _ahu(10 * DAY, seed=0, damper_stuck=0.1)
    frame = healthy.copy()
    frame.iloc[7 * DAY:] = stuck.iloc[7 * DAY:]
    return frame


def _episode(start="2026-01-13T00:00:00Z", end="2026-01-14T00:00:00Z", **extra) -> dict:
    return {"rule_id": "ECON-STUCK-DEMO", "verdict": "fault", "site_id": "demo-site", "equipment_id": "AHU-1",
            "start_utc": start, "end_utc": end, "tuners": {"damper_min_fraction": 0.1}, **extra}


CUT = pd.Timestamp("2026-01-11T00:00:00Z")


def test_ml_corroborates_a_real_fault_and_keeps_the_sql_verdict():
    frame = _history()
    r = review_episode(_episode(), frame, train=frame[frame.index < CUT], training={"source": "cutoff"})
    assert r["outcome"] == "corroborated" and r["sql_verdict"] == "fault" and r["sql_verdict_kept"]
    gb = r["methods"]["grey_box"]
    assert gb["status"] == "corroborates" and gb["assessed_coverage"] >= 0.5 and gb["flagged_share"] >= 0.25
    assert "oa_fraction" in gb["residuals_median_abs"]
    assert r["episode"]["tuners"] == {"damper_min_fraction": 0.1}  # original evidence carried unchanged


def test_quiet_ml_is_needs_review_never_a_false_positive():
    frame = _ahu(10 * DAY)  # no fault anywhere; the 'SQL episode' sits on healthy data
    r = review_episode(_episode(), frame, train=frame[frame.index < CUT], training={"source": "cutoff"})
    assert r["outcome"] == "needs_review" and r["report_inclusion"] == "keep"
    assert any(x["code"] == "ml_quiet" for x in r["reasons"])
    assert "false_positive" not in json.dumps({k: v for k, v in r.items() if k != "policy"})


def test_a_baseline_that_learned_the_fault_cannot_discard_it():
    stuck = _ahu(10 * DAY, damper_stuck=0.1)  # the 'known-good' folder already has the damper stuck
    frame = _history()
    r = review_episode(_episode(), frame, train=stuck.iloc[:7 * DAY], training={"source": "folder"})
    assert r["methods"]["grey_box"]["status"] == "quiet"
    assert r["outcome"] == "needs_review" and r["sql_verdict_kept"] and r["report_inclusion"] == "keep"


@pytest.mark.parametrize("case, code", [
    ("no_training", "training_source_missing"),
    ("overlap", "training_overlaps_episode"),
    ("fan_off", "no_active_rows"),
    ("empty_window", "no_data_in_window"),
    ("unassessed_sql", "sql_episode_unassessed"),
])
def test_insufficient_evidence_with_reasons(case, code):
    frame = _history()
    train = frame[frame.index < CUT]
    episode = _episode()
    if case == "no_training":
        train = None
    elif case == "overlap":
        train = frame[frame.index < pd.Timestamp("2026-01-13T12:00:00Z")]
    elif case == "fan_off":
        frame.loc["2026-01-13":"2026-01-13 23:55", ["fan-status", "fan-cmd"]] = 0.0
        train = frame[frame.index < CUT]
    elif case == "empty_window":
        episode = _episode("2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    elif case == "unassessed_sql":
        episode = _episode(run_proof=False)
    r = review_episode(episode, frame, train=train, training={"source": "test"})
    assert r["outcome"] == "insufficient_evidence" and r["sql_verdict_kept"]
    assert code in [x["code"] for x in r["reasons"]] and r["methods"] == {}


def test_missing_features_leave_every_method_unassessed():
    frame = _history()
    train = frame[frame.index < CUT].copy()
    later = frame.index >= CUT
    for col in ("mixed-air-temp", "return-air-temp", "discharge-air-temp", "cooling-valve"):
        frame.loc[later, col] = np.nan
    r = review_episode(_episode(), frame, train=train, training={"source": "cutoff"})
    assert r["outcome"] == "insufficient_evidence"
    assert any(x["code"] == "no_method_assessed" for x in r["reasons"])
    assert {v["status"] for v in r["methods"].values()} <= {"unassessed", "unsupported"}


def _folder(tmp_path: Path, frame: pd.DataFrame, name: str = "AHU_1") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    frame.to_csv(folder / "history_wide.csv", index_label="timestamp_utc")
    points = {c: c for c in frame.columns}
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": points}), encoding="utf-8")
    return folder


def test_cli_writes_a_reproducible_review(tmp_path, capsys):
    folder = _folder(tmp_path, _history())
    ep = tmp_path / "episode.json"
    ep.write_text(json.dumps(_episode()), encoding="utf-8")
    out = tmp_path / "review.json"
    assert main([str(ep), str(folder), "--train-until", "2026-01-11", "--methods", "grey_box,pca",
                 "--out", str(out)]) == 0
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["outcome"] == "corroborated" and r["training"]["source"] == "cutoff"
    assert "operator-asserted" in r["training"]["assertion"]
    assert len(r["inputs"]["episode_sha256"]) == 64 and r["inputs"]["folder"]["history_wide.csv"]
    capsys.readouterr()
    assert main([str(ep), str(folder)]) == 0  # no training source: a review, not a crash
    assert json.loads(capsys.readouterr().out)["outcome"] == "insufficient_evidence"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"rule_id": "X"}), encoding="utf-8")
    assert main([str(bad), str(folder), "--train-until", "2026-01-11"]) == 2
    assert "lacks" in capsys.readouterr().err
