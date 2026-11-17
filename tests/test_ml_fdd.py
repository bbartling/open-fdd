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
    rat = 22 + rng.normal(0, 0.2, n)
    damper = np.clip(0.1 + 0.8 * (oat < 15) * (oat > 2), 0.1, 1.0)
    actual = damper if damper_stuck is None else np.full(n, damper_stuck)
    mat = actual * oat + (1 - actual) * rat + rng.normal(0, 0.1, n)
    valve = np.clip((mat - 13) / 10, 0, 1)
    sat = mat - 10 * valve + rng.normal(0, 0.1, n) + sat_bias
    return pd.DataFrame({
        "discharge-air-temp": sat, "discharge-air-temp-sp": 13.0, "mixed-air-temp": mat, "return-air-temp": rat,
        "outside-air-temp": oat, "outside-air-damper": damper, "cooling-valve": valve, "fan-cmd": 0.7 + 0.1 * valve,
        "fan-status": 1.0, "occupied": 1.0,
    }, index=idx)


# ---- LBNL loader ------------------------------------------------------------------------------------------------

def test_fixture_maps_to_si_roles_and_fixes_static_units():
    normal = lbnl.load_sdahu_csv(NORMAL_CSV)
    fault = lbnl.load_sdahu_csv(FAULT_CSV)
    assert len(normal) == len(fault) == 576
    assert str(normal.index.tz) == "UTC"
    for frame in (normal, fault):
        assert set(r for r, _ in lbnl.SDAHU_ROLE_MAP.values()) <= set(frame.columns)
        assert frame["duct-static-pressure-sp"].round(0).unique().tolist() == [400.0]  # both units -> Pa
        on = active_mask(frame)
        assert 200 < frame.loc[on, "duct-static-pressure"].median() < 500
        assert 10 < frame.loc[on, "discharge-air-temp"].median() < 16  # 55 °F setpoint -> about 12.9 °C
    assert fault["cooling-valve"].between(0, 1).all()


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
    frame = canonical_roles(pd.DataFrame({"sat": [1.0], "clg_valve_pct": [0.5], "oa_damper_pct": [0.9]}))
    assert {"discharge-air-temp", "cooling-valve", "outside-air-damper"} <= set(frame.columns)
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
    assert contrib[flags].mean().idxmax() == "discharge-air-temp"


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
    frame.iloc[500, frame.columns.get_loc("return-air-temp")] += 5.0
    flags = RollingAnomaly(kind="zscore").flags(frame)
    assert bool(flags.iloc[500])


def test_ocsvm_is_mode_gated():
    pytest.importorskip("sklearn")
    det = make_detector("ocsvm").fit(_synthetic_ahu(seed=7))
    assert set(det.models_) <= {"min_oa", "econ_only", "mech_min_oa", "econ_mech"} and det.models_
    healthy = det.flags(_synthetic_ahu(seed=8)).mean()
    biased = det.flags(_synthetic_ahu(seed=9, sat_bias=3.0)).mean()
    assert biased > healthy + 0.3


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
    wide = pd.read_csv(train / "history_wide.csv").drop(columns=["mixed_air_temp"])
    wide.to_csv(target / "history_wide.csv", index=False)
    cmap = json.loads((train / "column_map.json").read_text(encoding="utf-8"))
    cmap["points"].pop("mixed-air-temp")
    (target / "column_map.json").write_text(json.dumps(cmap), encoding="utf-8")
    assert main(["detect", str(target), "--method", "pca", "--train", str(train), "--out", str(tmp_path / "o")]) == 2
    assert "mixed-air-temp" in capsys.readouterr().err


def test_cli_detect_untrained_method_accepts_a_partial_folder(tmp_path):
    from open_fdd.ml.cli import main

    full = _device_folder(tmp_path)
    part = tmp_path / "AHU_3"
    part.mkdir()
    pd.read_csv(full / "history_wide.csv").drop(columns=["mixed_air_temp"]).to_csv(part / "history_wide.csv", index=False)
    cmap = json.loads((full / "column_map.json").read_text(encoding="utf-8"))
    cmap["points"].pop("mixed-air-temp")
    (part / "column_map.json").write_text(json.dumps(cmap), encoding="utf-8")
    assert main(["detect", str(part), "--method", "zscore", "--out", str(tmp_path / "z")]) == 0


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
