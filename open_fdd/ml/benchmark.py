"""LBNL single-duct AHU benchmark: the rule pack vs ML / statistical detectors, scored with LBNL-style metrics.

Protocol (deterministic; see docs/ml/lbnl-ahu-benchmark.md):

1. Load the fault-free file and each faulted file of the subset (:data:`open_fdd.ml.lbnl.SDAHU_SUBSET`), 1-minute
   rows subsampled to a 5-minute poll, mapped to SI Open-FDD roles.
2. Split by ISO week: odd weeks train, even weeks test. Detectors that learn are fitted on the *fault-free* file's
   odd weeks only (active rows). Nothing learns from a faulted file.
3. Every method produces 5-minute flags for every file. Flags become one-hour evaluation samples (operating at
   least half the hour; flagged when at least 25 % of the active points are flagged). Only even (test) weeks count.
4. FPR comes from the fault-free file, TPR and detection delay from each faulted file.

Rule rows: ``rules (all)`` is the union of every AHU rule that confirmed a fault; ``rules (tuned)`` drops rules
whose one-hour FPR on the fault-free *training* weeks is above ``suppress_fpr`` (5 %), the way an engineer would
silence design-level advisories on a unit known to be healthy. The ML thresholds get the same training data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from open_fdd.ml import lbnl
from open_fdd.ml.baseline import RulePackRun, run_rule_pack
from open_fdd.ml.detectors import FEATURE_ROLES, active_mask, copod_available, make_detector
from open_fdd.ml.metrics import DEFAULT_PERSISTENCE, DEFAULT_WINDOW, score_file, window_decisions

DEFAULT_METHODS = ("rules", "pca", "grey_box", "ocsvm", "copod", "zscore", "mad")
METHOD_ORDER = ("rules (all)", "rules (tuned)", "pca", "grey_box", "ocsvm", "copod", "zscore", "mad")
SUPPRESS_FPR = 0.05
#: Duct static is left out of the benchmark features: its unit and behavior differ between the published
#: fault-free file (nearly constant, Pa) and every faulted file (inches of water, varying), so a model trained on
#: the fault-free file would flag every faulted file for that reason alone, whatever the fault.
BENCHMARK_ROLES = tuple(r for r in FEATURE_ROLES if r != "duct-static-pressure")


def test_weeks(index: pd.DatetimeIndex) -> pd.Series:
    """True on even ISO weeks (the test split)."""
    week = pd.Series(index.isocalendar().week.to_numpy(), index=index).astype(int)
    return (week % 2) == 0


@dataclass
class BenchmarkResult:
    files: list[lbnl.LbnlFile]
    scores: list[dict] = field(default_factory=list)  # one per (method, file)
    rule_status: dict[str, str] = field(default_factory=dict)
    suppressed_rules: dict[str, float] = field(default_factory=dict)
    rule_hits: dict[str, dict[str, int]] = field(default_factory=dict)  # file -> rule -> test windows flagged
    skipped_methods: dict[str, str] = field(default_factory=dict)
    pca_contributions: dict[str, dict[str, float]] = field(default_factory=dict)
    timing_s: dict[str, float] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    data_checks: list[str] = field(default_factory=list)

    def table(self) -> pd.DataFrame:
        frame = pd.DataFrame(self.scores)
        return frame.pivot(index="method", columns="fault_file", values="rate") if not frame.empty else frame

    def to_json(self) -> dict:
        return {
            "files": [f.__dict__ for f in self.files], "scores": self.scores, "rule_status": self.rule_status,
            "suppressed_rules": self.suppressed_rules, "rule_hits": self.rule_hits,
            "skipped_methods": self.skipped_methods, "pca_contributions": self.pca_contributions,
            "timing_s": self.timing_s, "settings": self.settings, "data_checks": self.data_checks,
        }


def run_benchmark(
    cache_dir: Path | str | None = None,
    *,
    files: Iterable[lbnl.LbnlFile] = lbnl.SDAHU_SUBSET,
    methods: Iterable[str] = DEFAULT_METHODS,
    frames: dict[str, pd.DataFrame] | None = None,
    window: str = DEFAULT_WINDOW,
    persistence: float = DEFAULT_PERSISTENCE,
    suppress_fpr: float = SUPPRESS_FPR,
    seed: int = 0,
    roles: tuple[str, ...] = BENCHMARK_ROLES,
    download: bool = False,
    log: Callable[[str], None] | None = print,
) -> BenchmarkResult:
    """Run the benchmark on cached LBNL files (or on prepared ``frames``: ``{file name: role frame}``)."""
    files = list(files)
    if not files or files[0].fault != "none":
        raise ValueError("the first file must be the fault-free run")
    say = log or (lambda _msg: None)
    result = BenchmarkResult(files=files, settings={"window": window, "persistence": persistence,
                                                    "suppress_fpr": suppress_fpr, "seed": seed, "step_minutes": 5,
                                                    "roles": list(roles)})
    if frames is None:
        cache = Path(cache_dir) if cache_dir is not None else lbnl.default_cache_dir()
        if download:
            lbnl.download([f.name for f in files], cache, log=say)
        frames = {}
        for f in files:
            path = cache / f.name
            if not path.is_file():
                raise FileNotFoundError(f"{path} missing; run `open-fdd-ml download` first")
            t0 = time.time()
            frames[f.name] = lbnl.load_sdahu_csv(path)
            say(f"loaded {f.name}: {len(frames[f.name])} rows in {time.time() - t0:.1f}s")

    selected = [f.name for f in files]
    missing = [name for name in selected if name not in frames]
    if missing:
        raise ValueError(f"no frame for selected file(s): {', '.join(missing)}")
    frames = {name: frames[name] for name in selected}
    normal_name = files[0].name
    normal = frames[normal_name]
    train_rows = normal[~test_weeks(normal.index)]
    actives = {name: active_mask(frame) for name, frame in frames.items()}
    by_name = {f.name: f for f in files}

    def decisions(name: str, flags: pd.Series) -> pd.Series:
        dec = window_decisions(flags, actives[name], window=window, persistence=persistence)
        return dec[test_weeks(dec.index)]

    def record(method: str, name: str, flags: pd.Series) -> None:
        score = score_file(method, name, decisions(name, flags), is_fault=by_name[name].fault != "none")
        result.scores.append(score.to_dict())

    methods = [m.strip().lower() for m in methods if m.strip()]

    if "rules" in methods:
        t0 = time.time()
        runs: dict[str, RulePackRun] = {name: run_rule_pack(frame) for name, frame in frames.items()}
        result.rule_status = runs[normal_name].status
        for rule, mask in runs[normal_name].flags.items():
            dec = window_decisions(mask, actives[normal_name], window=window, persistence=persistence)
            train = dec[~test_weeks(dec.index)]
            fpr = float(train.mean()) if train.size else 0.0
            if fpr > suppress_fpr:
                result.suppressed_rules[rule] = fpr
        for name, run in runs.items():
            idx = frames[name].index
            record("rules (all)", name, run.union(idx))
            kept = [r for r in run.flags if r not in result.suppressed_rules]
            record("rules (tuned)", name, run.union(idx, kept))
            result.rule_hits[name] = {rule: int(decisions(name, mask).sum()) for rule, mask in run.flags.items()}
        result.timing_s["rules"] = time.time() - t0
        say(f"rules: {result.timing_s['rules']:.1f}s, suppressed {sorted(result.suppressed_rules)}")

    for method in methods:
        if method == "rules":
            continue
        if method == "copod" and not copod_available():
            result.skipped_methods["copod"] = "pyod not installed"
            say("copod skipped: pyod not installed")
            continue
        t0 = time.time()
        try:
            det = make_detector(method, seed=seed, roles=roles)
            if det.needs_training:
                det.fit(train_rows)
        except (ImportError, ValueError) as exc:
            result.skipped_methods[method] = str(exc)
            say(f"{method} skipped: {exc}")
            continue
        for name, frame in frames.items():
            flags = det.flags(frame)
            record(method, name, flags)
            if method == "pca":
                contrib = det.contributions(frame)  # type: ignore[attr-defined]
                test = test_weeks(frame.index) & flags
                if test.any():
                    result.pca_contributions[name] = {k: float(v) for k, v in contrib[test].mean().items()}
        result.timing_s[method] = time.time() - t0
        say(f"{method}: {result.timing_s[method]:.1f}s")

    # published-data checks a reader should know about
    if "oa_bias_4_annual.csv" in frames:
        diff = (frames["oa_bias_4_annual.csv"]["outside-air-temp"] - normal["outside-air-temp"]).dropna()
        result.data_checks.append(f"oa_bias file minus fault-free OAT: median {diff.median():+.2f} °C")
    if "coi_bias_4_annual.csv" in frames:
        diff = (frames["coi_bias_4_annual.csv"]["discharge-air-temp"] - normal["discharge-air-temp"])
        diff = diff[actives[normal_name]].dropna()
        result.data_checks.append(f"coi_bias_4 file minus fault-free SAT (fan on): median {diff.median():+.2f} °C")
    return result


def _pct(value) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{100.0 * float(value):.1f}"


def to_markdown(result: BenchmarkResult) -> str:
    """The results as Markdown: TPR / FPR table and detection delay table."""
    frame = pd.DataFrame(result.scores)
    if frame.empty:
        return "(no scores)\n"
    normal = result.files[0].name
    present = set(frame["fault_file"])
    faults = [f for f in result.files[1:] if f.name in present]
    order = [m for m in METHOD_ORDER if m in set(frame["method"])]
    rate = frame.pivot(index="method", columns="fault_file", values="rate")
    delay = frame.pivot(index="method", columns="fault_file", values="delay_h")
    head = ["Method", "FPR % (fault-free)"] + [f"TPR % {f.fault} {f.intensity}" for f in faults] + ["Mean TPR %"]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for m in order:
        tprs = [rate.loc[m, f.name] for f in faults]
        mean = sum(tprs) / len(tprs) if tprs else None
        lines.append("| " + " | ".join([f"`{m}`", _pct(rate.loc[m, normal])] + [_pct(v) for v in tprs] + [_pct(mean)]) + " |")
    n_eval = int(frame[frame["fault_file"] == normal]["samples"].iloc[0])
    lines += ["", f"Evaluation samples: one-hour windows in even ISO weeks with the fan on and occupied "
                  f"({n_eval} windows in the fault-free file).", ""]
    dhead = ["Method"] + [f"{f.fault} {f.intensity}" for f in faults]
    lines += ["Detection delay, hours from the first test window (early January) to the first flagged window:", "",
              "| " + " | ".join(dhead) + " |", "|" + "|".join(["---"] * len(dhead)) + "|"]
    for m in order:
        cells = []
        for f in faults:
            v = delay.loc[m, f.name]
            cells.append("never" if v is None or pd.isna(v) else f"{float(v):.0f}")
        lines.append("| " + " | ".join([f"`{m}`"] + cells) + " |")
    if result.suppressed_rules:
        lines += ["", "`rules (tuned)` leaves out, by their one-hour FPR on the fault-free training weeks: "
                  + ", ".join(f"{r} ({100 * v:.0f} %)" for r, v in sorted(result.suppressed_rules.items())) + "."]
    if result.rule_hits:
        lines += ["", "Rules that confirmed a fault, by test windows flagged (top 4 per file):", "",
                  "| File | Rules (windows) |", "|---|---|"]
        for f in result.files:
            hits = result.rule_hits.get(f.name, {})
            top = sorted(((n, r) for r, n in hits.items() if n), reverse=True)[:4]
            lines.append(f"| {f.fault} {f.intensity} | " + (", ".join(f"{r} ({n})" for n, r in top) or "none") + " |")
    if result.skipped_methods:
        lines += ["", "Skipped: " + "; ".join(f"`{m}`: {why}" for m, why in result.skipped_methods.items()) + "."]
    if result.data_checks:
        lines += ["", "Data checks: " + "; ".join(result.data_checks) + "."]
    return "\n".join(lines) + "\n"
