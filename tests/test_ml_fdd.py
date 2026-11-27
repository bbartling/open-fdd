"""open_fdd.ml: LBNL loader, metrics, detectors, rule-pack baseline, benchmark and the open-fdd-ml CLI.

Uses the tiny committed LBNL fixture (tests/fixtures/lbnl_sdahu, CC BY 4.0) and seeded synthetic frames; never
the network. scikit-learn tests skip without the ``ml`` extra, COPOD tests without ``pyod``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from open_fdd.ml import lbnl, metrics  # noqa: E402
from open_fdd.ml.detectors import (  # noqa: E402
    GreyBox,
    PCASPE,
    RollingAnomaly,
    active_mask,
    canonical_roles,
    copod_available,
    make_detector,
    operating_mode,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lbnl_sdahu"
NORMAL_CSV = FIXTURE / "AHU_annual_2018-07-03_10.csv"
FAULT_CSV = FIXTURE / "coi_stuck_050_annual_2018-07-03_10.csv"


def _synthetic_ahu(n: int = 2000, seed: int = 0, sat_bias: float = 0.0, damper_stuck: float | None = None):
    """A seeded AHU frame that obeys the mixed-air balance and a simple coil model (SI, roles)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    oat = 10 + 12 * np.sin(np.arange(n) / 288 * 2 * np.pi) + rng.normal(0, 0.3, n)
    return_air_temperature = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    actual = damper if damper_stuck is None else np.full(n, damper_stuck)
    mixed_air_temperature = actual * oat + (1 - actual) * return_air_temperature + rng.normal(0, 0.1, n)
    valve = np.clip((mixed_air_temperature - 13) / 10, 0, 1)
    discharge_air_temperature = mixed_air_temperature - 10 * valve + rng.normal(0, 0.1, n) + sat_bias
    return pd.DataFrame({
        "discharge_air_temperature": discharge_air_temperature, "discharge_air_temperature_setpoint": 13.0, "mixed_air_temperature": mixed_air_temperature, "return_air_temperature": return_air_temperature,
        "outdoor_air_intake_temperature": oat, "outdoor_air_intake_damper_position_command": damper, "cooling_valve_position_command": valve, "supply_fan_command": 0.7 + 0.1 * valve,
        "supply_fan_operating_status": 1.0, "occupancy_status": 1.0,
    }, index=idx)


# ---- LBNL loader ------------------------------------------------------------------------------------------------

def test_fixture_maps_to_si_roles_and_fixes_static_units():
    normal = lbnl.load_sdahu_csv(NORMAL_CSV)
    fault = lbnl.load_sdahu_csv(FAULT_CSV)
    assert len(normal) == len(fault) == 576
    assert str(normal.index.tz) == "UTC"
    for frame in (normal, fault):
        assert set(r for r, _ in lbnl.SDAHU_ROLE_MAP.values()) <= set(frame.columns)
        assert frame["discharge_air_static_pressure_setpoint"].round(0).unique().tolist() == [400.0]  # both units -> Pa
        on = active_mask(frame)
        assert 200 < frame.loc[on, "discharge_air_static_pressure"].median() < 500
        assert 10 < frame.loc[on, "discharge_air_temperature"].median() < 16  # 55 °F setpoint -> about 12.9 °C
        assert fault["cooling_valve_position_command"].between(0, 100).all()
        assert "supply_fan_speed_command" in frame.columns


def test_static_to_pa_detects_unit():
    s = pd.Series([1.5, 1.6, 1.7])
    assert lbnl.static_to_pa(s).round(1).tolist() == [373.6, 398.5, 423.5]
    assert lbnl.static_to_pa(pd.Series([400.0, 401.0])).tolist() == [400.0, 401.0]
    assert lbnl.static_to_pa(pd.Series([-400.25]), setpoint=True).tolist() == [400.25]


def test_download_uses_cache_without_network(tmp_path, monkeypatch):
    (tmp_path / "AHU_annual.csv").write_text("Datetime\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise AssertionError("network used")

    monkeypatch.setattr(lbnl, "_HttpRangeFile", boom)
    assert lbnl.download(["AHU_annual.csv"], tmp_path, log=None) == [tmp_path / "AHU_annual.csv"]


def test_default_cache_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFDD_ML_CACHE", str(tmp_path))
    assert lbnl.default_cache_dir() == tmp_path


def test_subset_attribution_and_fault_free_first():
    assert lbnl.SDAHU_SUBSET[0].fault == "none"
    assert "CC BY 4.0" in lbnl.ATTRIBUTION and "10.25984/1881324" in lbnl.ATTRIBUTION


# ---- metrics ----------------------------------------------------------------------------------------------------

def test_window_decisions_persistence_and_activity():
    idx = pd.date_range("2026-01-05", periods=24, freq="5min", tz="UTC")  # two hours
    flags = pd.Series([True] * 3 + [False] * 9 + [True] * 2 + [False] * 10, index=idx)
    active = pd.Series(True, index=idx)
    dec = metrics.window_decisions(flags, active)
    assert dec.tolist() == [True, False]  # 3/12 = 25 % flags the hour, 2/12 does not
    inactive = active.copy()
    inactive.iloc[12:] = False
    assert metrics.window_decisions(flags, inactive).size == 1  # the idle hour is not a sample


def test_window_decisions_one_sample_does_not_qualify_an_hour():
    """#1666: one observed 5-minute sample is 1/12 of the hour's elapsed time, below the 50 % eligibility."""
    idx = pd.DatetimeIndex(["2026-01-05T00:00:00Z"])
    flags = pd.Series([True], index=idx)
    active = pd.Series([True], index=idx)
    assert metrics.window_decisions(flags, active).size == 0
    cov = metrics.window_coverage(flags, active)
    assert cov["observed"].tolist() == [1] and cov["expected"].tolist() == [12.0]
    assert not bool(cov["eligible"].iloc[0]) and pd.isna(cov["decision"].iloc[0])
    # a declared hourly cadence makes one sample a fully observed hour
    assert metrics.window_decisions(flags, active, cadence="1h").tolist() == [True]


def test_window_coverage_gaps_duplicates_proof_and_boundaries():
    base = pd.date_range("2026-01-05", periods=48, freq="5min", tz="UTC")  # four hours
    keep = np.ones(48, dtype=bool)
    keep[3:9] = False      # hour 0: 6 of 12 present (middle gap) -> exactly 50 %, eligible
    keep[19:24] = False    # hour 1: 7 of 12 present (end gap) -> eligible
    keep[24:31] = False    # hour 2: 5 of 12 present (start gap) -> ineligible
    idx = base[keep]
    flags = pd.Series(False, index=idx)
    active = pd.Series(True, index=idx)
    active[idx >= base[36]] = False
    active[idx >= base[42]] = True       # hour 3: 6 of 12 active (proof gap) -> eligible
    flags[idx == base[43]] = True
    flags[idx == base[44]] = True        # 2 of 6 active flagged = 33 % of active time (10 of 60 minutes)
    dup = pd.Series([True], index=[base[0]])
    flags = pd.concat([flags, dup])      # a duplicate timestamp counts once (last value wins)
    active = pd.concat([active, pd.Series([True], index=[base[0]])])
    cov = metrics.window_coverage(flags, active, cadence="5min")
    assert cov["observed"].tolist() == [6, 7, 5, 12]
    assert cov["active"].tolist() == [6, 7, 5, 6]
    assert cov["eligible"].tolist() == [True, True, False, True]
    assert cov["decision"].iloc[0] == False and pd.isna(cov["decision"].iloc[2]) and cov["decision"].iloc[3] == True
    dec = metrics.window_decisions(flags, active)  # inferred cadence matches the declared one
    assert dec.tolist() == [False, False, True]  # hour 0: 1 of 6 active flagged (17 %) is below 25 %
    # boundary: data starting at :40 leaves 4 samples in its first hour -> not an evaluation sample
    late = pd.date_range("2026-01-05T00:40", periods=16, freq="5min", tz="UTC")
    cov = metrics.window_coverage(pd.Series(False, index=late), pd.Series(True, index=late))
    assert cov["observed"].tolist() == [4, 12] and cov["eligible"].tolist() == [False, True]


def test_score_file_rate_and_delay():
    idx = pd.date_range("2026-01-05", periods=4, freq="1h", tz="UTC")
    dec = pd.Series([False, False, True, True], index=idx)
    s = metrics.score_file("m", "f", dec, is_fault=True)
    assert (s.samples, s.flagged, s.rate, s.delay_h) == (4, 2, 0.5, 2.0)
    assert metrics.score_file("m", "f", dec, is_fault=False).delay_h is None


def test_split_weeks_alternates():
    idx = pd.date_range("2026-01-05", periods=21, freq="1D", tz="UTC")  # ISO weeks 2, 3, 4
    train, test = metrics.split_weeks(idx)
    assert train.sum() == 7 and test.sum() == 14


# ---- detectors --------------------------------------------------------------------------------------------------

def test_canonical_roles_and_modes():
    frame = canonical_roles(pd.DataFrame({"discharge_air_temperature": [1.0], "cooling_valve_position_command": [0.5], "outdoor_air_intake_damper_position_command": [0.9]}))
    assert {"discharge_air_temperature", "cooling_valve_position_command", "outdoor_air_intake_damper_position_command"} <= set(frame.columns)
    assert operating_mode(frame).tolist() == ["econ_mech"]


def test_pca_spe_flags_a_biased_sensor_and_explains_it():
    normal = _synthetic_ahu(seed=1)
    det = PCASPE().fit(normal)
    assert 0.0 < det.flags(normal).mean() < 0.03  # about the 1 % training quantile
    healthy = det.flags(_synthetic_ahu(seed=12)).mean()
    faulty = _synthetic_ahu(seed=2, sat_bias=3.0)
    flags = det.flags(faulty)
    assert flags.mean() > max(0.1, 5 * healthy)
    contrib = det.contributions(faulty)
    assert np.allclose(contrib.dropna().sum(axis=1), 1.0)
    assert contrib[flags].mean().idxmax() == "discharge_air_temperature"


def test_grey_box_residuals_catch_a_stuck_damper():
    det = GreyBox().fit(_synthetic_ahu(seed=3))
    assert set(det.thresholds_) >= {"oa_fraction", "coil_delta_t"}
    healthy = det.flags(_synthetic_ahu(seed=4)).mean()
    stuck = det.flags(_synthetic_ahu(seed=5, damper_stuck=0.1)).mean()
    assert healthy < 0.05 and stuck > healthy + 0.2


def test_grey_box_without_usable_residuals_raises():
    with pytest.raises(ValueError, match="learned no residual"):
        GreyBox().fit(_synthetic_ahu(n=10, seed=3))


def test_grey_box_refit_drops_the_earlier_baseline():
    det = GreyBox().fit(_synthetic_ahu(seed=3))
    assert det.thresholds_
    with pytest.raises(ValueError, match="learned no residual"):
        det.fit(_synthetic_ahu(n=10, seed=4))
    assert det.thresholds_ == {}
    with pytest.raises(RuntimeError, match="not fitted"):
        det.flags(_synthetic_ahu(seed=5))
    with pytest.raises(RuntimeError, match="not fitted"):
        GreyBox().scores(_synthetic_ahu(seed=5))


def test_rolling_adapter_uses_existing_detectors():
    frame = _synthetic_ahu(seed=6)
    frame.iloc[500, frame.columns.get_loc("return_air_temperature")] += 5.0
    flags = RollingAnomaly(kind="zscore").flags(frame)
    assert bool(flags.iloc[500])


def test_ocsvm_is_mode_gated():
    pytest.importorskip("sklearn")
    det = make_detector("ocsvm").fit(_synthetic_ahu(seed=7))
    assert set(det.models_) <= {"min_oa", "econ_only", "mech_min_oa", "econ_mech"} and det.models_
    healthy = det.flags(_synthetic_ahu(seed=8)).mean()
    biased = det.flags(_synthetic_ahu(seed=9, sat_bias=3.0)).mean()
    assert biased > healthy + 0.3


def _mode_rows(mode: str, n: int = 60, seed: int = 20) -> "pd.DataFrame":
    """``n`` synthetic AHU rows that are all in one operating mode (see ``operating_mode``)."""
    frame = _synthetic_ahu(n=4000, seed=seed)
    rows = frame[operating_mode(frame) == mode]
    assert len(rows) >= n, f"synthetic AHU has only {len(rows)} {mode} rows"
    return rows.iloc[:n]


def test_mode_gated_refit_replaces_every_mode_model():
    """#1666: old-mode fit -> new-mode refit -> old-mode scoring is unassessed, never served by the old model."""
    pytest.importorskip("sklearn")
    det = make_detector("ocsvm")
    det.fit(_mode_rows("econ_only"))
    assert set(det.models_) == {"econ_only"} and det.fit_revision_ == 1
    det.fit(_mode_rows("mech_min_oa"))
    assert set(det.models_) == {"mech_min_oa"}, "a refit kept a model from the earlier fit"
    assert set(det.mode_columns_) == {"mech_min_oa"}
    assert det.fit_revision_ == 2
    assert det.fit_receipt_["status"] == "fitted"
    assert {m: v["revision"] for m, v in det.fit_receipt_["modes"].items()} == {"mech_min_oa": 2}
    old_mode = _mode_rows("econ_only", seed=21)
    assessment = det.assessment(old_mode)
    assert (assessment == "unsupported_mode").all()
    assert not det.assessed_mask(old_mode).any()
    assert not det.flags(old_mode).any()  # unassessed rows carry no flag; the assessment says why


def test_mode_gated_failed_refit_leaves_no_usable_model():
    pytest.importorskip("sklearn")
    det = make_detector("ocsvm").fit(_mode_rows("econ_only"))
    with pytest.raises(ValueError, match="no operating mode had 50"):
        det.fit(_mode_rows("econ_only", n=20, seed=22))
    assert not det.is_fitted and det.models_ == {} and det.roles == []
    assert det.fit_receipt_["status"] == "failed" and det.fit_revision_ == 1
    assert "econ_only" in det.fit_receipt_["skipped_modes"]
    for call in (det.flags, det.scores, det.assessment):
        with pytest.raises(RuntimeError, match="not fitted"):
            call(_mode_rows("econ_only", seed=23))
    with pytest.raises(RuntimeError, match="not fitted"):
        make_detector("ocsvm").flags(_mode_rows("econ_only", seed=23))


def test_mode_gated_assessment_reasons():
    pytest.importorskip("sklearn")
    det = make_detector("ocsvm").fit(_synthetic_ahu(seed=24))
    frame = _synthetic_ahu(n=300, seed=25)
    frame.iloc[:10, frame.columns.get_loc("supply_fan_operating_status")] = 0.0
    frame.iloc[10:20, frame.columns.get_loc(det.roles[0])] = np.nan
    assessment = det.assessment(frame)
    assert (assessment.iloc[:10] == "inactive").all()
    assert (assessment.iloc[10:20] == "missing_inputs").all()
    supported = operating_mode(frame).isin(list(det.models_))
    rest = assessment.iloc[20:]
    assert (rest[supported.iloc[20:]] == "assessed").all()
    assert (rest[~supported.iloc[20:]] == "unsupported_mode").all()
    flags = det.flags(frame)
    assert not flags[assessment != "assessed"].any()
    assert det.fit_receipt_["roles"] == det.roles and det.fit_receipt_["seed"] == 0


def test_copod_optional():
    if not copod_available():
        with pytest.raises(ImportError):
            make_detector("copod")
        return
    det = make_detector("copod").fit(_synthetic_ahu(seed=10))
    assert det.flags(_synthetic_ahu(seed=11)).dtype == bool


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        make_detector("nope")


# ---- baseline + benchmark ---------------------------------------------------------------------------------------

def _fixture_frames():
    return {
        "AHU_annual.csv": lbnl.load_sdahu_csv(NORMAL_CSV),
        "coi_stuck_050_annual.csv": lbnl.load_sdahu_csv(FAULT_CSV),
    }


FIXTURE_FILES = [lbnl.SDAHU_SUBSET[0], next(f for f in lbnl.SDAHU_SUBSET if f.name == "coi_stuck_050_annual.csv")]


def test_rule_pack_baseline_runs_the_ahu_rules():
    from open_fdd.ml.baseline import ahu_rule_ids, run_rule_pack

    ids = ahu_rule_ids()
    assert "FC1" in ids and "ECON-1" in ids
    run = run_rule_pack(lbnl.load_sdahu_csv(FAULT_CSV))
    assert run.status["FC1"] in {"PASS", "FAULT"}
    assert not any(s.startswith("ERROR") for s in run.status.values())
    assert run.union(lbnl.load_sdahu_csv(FAULT_CSV).index).dtype == bool


def test_benchmark_on_fixture_is_deterministic():
    from open_fdd.ml.benchmark import run_benchmark, to_markdown

    methods = ["rules", "pca", "grey_box", "zscore"]
    first = run_benchmark(frames=_fixture_frames(), files=FIXTURE_FILES, methods=methods, log=None)
    second = run_benchmark(frames=_fixture_frames(), files=FIXTURE_FILES, methods=methods, log=None)
    assert first.scores == second.scores
    got = {(s["method"], s["fault_file"]) for s in first.scores}
    assert ("rules (all)", "AHU_annual.csv") in got and ("pca", "coi_stuck_050_annual.csv") in got
    text = to_markdown(first)
    assert "| `rules (tuned)` |" in text and "FPR % (fault-free)" in text
    json.dumps(first.to_json(), default=str)
    # #1666: excluded coverage is published next to the rates; samples never exceed eligible test windows
    assert set(first.coverage) == {f.name for f in FIXTURE_FILES}
    for name, cov in first.coverage.items():
        assert cov["eligible"] + cov["excluded_not_active_enough"] == cov["test_windows_observed"]
        assert all(s["samples"] == cov["eligible"] for s in first.scores if s["fault_file"] == name)


def test_benchmark_requires_fault_free_first():
    from open_fdd.ml.benchmark import run_benchmark

    with pytest.raises(ValueError):
        run_benchmark(frames=_fixture_frames(), files=FIXTURE_FILES[::-1], log=None)


def test_benchmark_uses_only_the_selected_files():
    from open_fdd.ml.benchmark import run_benchmark

    frames = _fixture_frames()
    only_normal = run_benchmark(frames=frames, files=FIXTURE_FILES[:1], methods=["zscore"], log=None)
    assert {s["fault_file"] for s in only_normal.scores} == {FIXTURE_FILES[0].name}
    with pytest.raises(ValueError, match="no frame"):
        run_benchmark(frames={FIXTURE_FILES[0].name: frames[FIXTURE_FILES[0].name]}, files=FIXTURE_FILES, log=None)


def test_range_reader_rejects_a_server_that_ignores_ranges(monkeypatch):
    class Resp:
        def __init__(self, status, headers, body=b""):
            self.status, self.headers, self._body = status, headers, body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n=-1):
            return self._body

    replies = [Resp(200, {"Content-Length": "100", "Accept-Ranges": "bytes"}), Resp(200, {}, b"x" * 100)]
    monkeypatch.setattr(lbnl.urllib.request, "urlopen", lambda req, timeout=None: replies.pop(0))
    reader = lbnl._HttpRangeFile("https://example.invalid/a.zip")
    with pytest.raises(OSError, match="206"):
        reader.read(10)
    monkeypatch.setattr(lbnl.urllib.request, "urlopen", lambda req, timeout=None: Resp(200, {}))
    with pytest.raises(OSError, match="Content-Length"):
        lbnl._HttpRangeFile("https://example.invalid/a.zip")


# ---- CLI --------------------------------------------------------------------------------------------------------

def _device_folder(tmp_path: Path) -> Path:
    frame = lbnl.load_sdahu_csv(NORMAL_CSV)
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    out = frame.copy()
    out.columns = [c.replace("-", "_") for c in out.columns]
    out.to_csv(folder / "history_wide.csv", index_label="timestamp_utc")
    points = {role: role.replace("-", "_") for role in frame.columns}
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": points}), encoding="utf-8")
    return folder


def test_cli_detect_writes_flags_and_contributions(tmp_path):
    from open_fdd.ml.cli import main

    folder = _device_folder(tmp_path)
    out = tmp_path / "out"
    assert main(["detect", str(folder), "--method", "pca", "--train-until", "2018-07-05", "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["method"] == "pca" and summary["train_rows"] == 288
    assert (out / "flags.csv").is_file() and (out / "contributions.csv").is_file()
    assert main(["detect", str(folder), "--method", "grey_box", "--train-until", "2018-07-05",
                 "--out", str(tmp_path / "gb")]) == 0


def test_cli_detect_rejects_a_folder_missing_a_trained_role(tmp_path, capsys):
    from open_fdd.ml.cli import main

    train = _device_folder(tmp_path)
    target = tmp_path / "AHU_2"
    target.mkdir()
    wide = pd.read_csv(train / "history_wide.csv").drop(columns=["mixed_air_temperature"])
    wide.to_csv(target / "history_wide.csv", index=False)
    cmap = json.loads((train / "column_map.json").read_text(encoding="utf-8"))
    cmap["points"].pop("mixed_air_temperature")
    (target / "column_map.json").write_text(json.dumps(cmap), encoding="utf-8")
    assert main(["detect", str(target), "--method", "pca", "--train", str(train), "--out", str(tmp_path / "o")]) == 2
    assert "mixed_air_temperature" in capsys.readouterr().err


def test_cli_detect_untrained_method_accepts_a_partial_folder(tmp_path):
    from open_fdd.ml.cli import main

    full = _device_folder(tmp_path)
    part = tmp_path / "AHU_3"
    part.mkdir()
    pd.read_csv(full / "history_wide.csv").drop(columns=["mixed_air_temperature"]).to_csv(part / "history_wide.csv", index=False)
    cmap = json.loads((full / "column_map.json").read_text(encoding="utf-8"))
    cmap["points"].pop("mixed_air_temperature")
    (part / "column_map.json").write_text(json.dumps(cmap), encoding="utf-8")
    assert main(["detect", str(part), "--method", "zscore", "--out", str(tmp_path / "z")]) == 0


def _folder_from_frame(tmp_path: Path, name: str, frame) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    out = frame.copy()
    out.columns = [c.replace("-", "_") for c in out.columns]
    out.to_csv(folder / "history_wide.csv", index_label="timestamp_utc")
    points = {role: role.replace("-", "_") for role in frame.columns}
    (folder / "column_map.json").write_text(json.dumps({"equipType": "AHU", "points": points}), encoding="utf-8")
    return folder


def _detect(tmp_path: Path, *argv: str):
    """Run ``open-fdd-ml detect``; return (exit code, summary or None, flags frame or None)."""
    from open_fdd.ml.cli import main

    out = tmp_path / f"out{len(list(tmp_path.glob('out*')))}"
    code = main(["detect", *argv, "--out", str(out)])
    if code != 0:
        return code, None, None
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    return code, summary, pd.read_csv(out / "flags.csv")


def test_cli_detect_learning_methods_require_a_training_source(tmp_path, capsys):
    """#1665: no silent self-fit. Learning methods exit 2 without --train/--train-until/--exploratory-self-fit."""
    folder = _device_folder(tmp_path)
    for method in ("pca", "grey_box", "ocsvm"):
        code, _, _ = _detect(tmp_path, str(folder), "--method", method)
        assert code == 2, method
        assert "--exploratory-self-fit" in capsys.readouterr().err
    code, summary, _ = _detect(tmp_path, str(folder), "--method", "zscore")
    assert code == 0 and summary["training"]["used"] is False and summary["train_rows"] == 0
    code, _, _ = _detect(tmp_path, str(folder), "--method", "pca", "--train", str(folder), "--train-until", "2018-07-05")
    assert code == 2  # mutually exclusive training sources


def test_cli_detect_cutoff_labels_phases_and_counts_evaluation_only(tmp_path):
    folder = _device_folder(tmp_path)
    code, summary, flags = _detect(tmp_path, str(folder), "--method", "pca", "--train-until", "2018-07-05")
    assert code == 0
    assert flags["phase"].value_counts().to_dict() == {"train": 288, "evaluation": 288}
    ev = flags[flags["phase"] == "evaluation"]
    assert summary["folder_rows"] == 576 and summary["rows"] == 288 and summary["train_rows"] == 288
    assert summary["flagged_rows"] == int(ev["flag"].sum()) and summary["active_rows"] == int(ev["active"].sum())
    assert summary["counts_cover"] == "evaluation rows only" and summary["exploratory"] is False
    t = summary["training"]
    assert t["source"] == "cutoff" and t["rows"] == 288 and t["active_rows"] > 0 and "operator-asserted" in t["assertion"]
    assert pd.Timestamp(t["end_utc"]) < pd.Timestamp(t["cutoff_utc"]) <= pd.Timestamp(summary["evaluation"]["start_utc"])
    assert summary["seed"] == 0 and summary["open_fdd_version"]


def test_cli_detect_rejects_empty_or_unusable_training_selections(tmp_path, capsys):
    folder = _device_folder(tmp_path)
    for cut, msg in (("2018-07-01", "no training rows"), ("2018-07-30", "no evaluation rows"),
                     ("not-a-date", "not a date")):
        code, _, _ = _detect(tmp_path, str(folder), "--method", "pca", "--train-until", cut)
        assert code == 2 and msg in capsys.readouterr().err, cut
    off = _synthetic_ahu(n=600, seed=30)
    off.iloc[:300, off.columns.get_loc("supply_fan_operating_status")] = 0.0
    off_folder = _folder_from_frame(tmp_path, "AHU_OFF", off)
    code, _, _ = _detect(tmp_path, str(off_folder), "--method", "pca", "--train-until", str(off.index[300].date()))
    assert code == 2 and "no active rows" in capsys.readouterr().err
    code, _, _ = _detect(tmp_path, str(folder), "--method", "pca", "--train", str(folder))
    assert code == 2 and "folder being scored" in capsys.readouterr().err


def test_cli_detect_discloses_and_excludes_training_overlap(tmp_path, capsys):
    frame = _synthetic_ahu(n=1200, seed=31)
    target = _folder_from_frame(tmp_path, "AHU_T", frame)
    copy = _folder_from_frame(tmp_path, "AHU_COPY", frame)
    code, _, _ = _detect(tmp_path, str(target), "--method", "pca", "--train", str(copy))
    assert code == 2 and "no held-out evaluation rows" in capsys.readouterr().err
    first_half = _folder_from_frame(tmp_path, "AHU_H", frame.iloc[:600])
    code, summary, flags = _detect(tmp_path, str(target), "--method", "pca", "--train", str(first_half))
    assert code == 0
    assert flags["phase"].value_counts().to_dict() == {"train_overlap": 600, "evaluation": 600}
    assert summary["training_overlap"]["identical_rows_excluded"] == 600 and summary["rows"] == 600
    other_device = _folder_from_frame(tmp_path, "AHU_OTHER", _synthetic_ahu(n=1200, seed=32))
    code, summary, flags = _detect(tmp_path, str(target), "--method", "pca", "--train", str(other_device))
    assert code == 0 and summary["training_overlap"]["common_timestamps"] == 1200
    assert summary["training_overlap"]["identical_rows_excluded"] == 0 and summary["rows"] == 1200


def test_cli_detect_persistent_fault_never_enters_the_cutoff_baseline(tmp_path):
    """A fault present in every evaluation row: the cutoff fit stays healthy and flags it; a self-fit absorbs it."""
    healthy = _synthetic_ahu(n=2016, seed=33)
    faulty = _synthetic_ahu(n=2016, seed=34, sat_bias=3.0)
    faulty.index = healthy.index + (healthy.index[-1] - healthy.index[0]) + pd.Timedelta(minutes=5)
    frame = pd.concat([healthy, faulty])
    folder = _folder_from_frame(tmp_path, "AHU_F", frame)
    cut = str(faulty.index[0])
    code, summary, flags = _detect(tmp_path, str(folder), "--method", "pca", "--train-until", cut)
    assert code == 0
    assert pd.Timestamp(summary["training"]["end_utc"]) < faulty.index[0]
    cutoff_rate = summary["flagged_rows"] / summary["active_rows"]
    code, self_summary, self_flags = _detect(tmp_path, str(folder), "--method", "pca", "--exploratory-self-fit")
    assert code == 0 and self_summary["exploratory"] is True and "warning" in self_summary["training"]
    assert set(self_flags["phase"]) == {"exploratory_self_fit"}
    ev = self_flags.set_index("timestamp_utc").loc[flags.loc[flags["phase"] == "evaluation", "timestamp_utc"]]
    self_rate = ev["flag"].sum() / ev["active"].sum()
    assert cutoff_rate > 0.1 and cutoff_rate > 3 * self_rate


def test_cli_benchmark_without_cache_is_a_clean_error(tmp_path, capsys):
    from open_fdd.ml.cli import main

    assert main(["benchmark", "--cache", str(tmp_path), "--methods", "pca"]) == 2
    assert "open-fdd-ml download" in capsys.readouterr().err


def test_cli_help_and_no_command():
    from open_fdd.ml.cli import main

    assert main([]) == 2
    assert main(["--help"]) == 0


def test_core_import_does_not_load_ml_dependencies():
    code = "import sys, open_fdd; print(any(m in sys.modules for m in ('sklearn', 'open_fdd.ml', 'pyod')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
