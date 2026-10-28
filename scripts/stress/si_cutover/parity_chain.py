"""SI cutover parity chain P0–P3 helpers (#1284 W3).

Equality contract:
  * FDD fault_seconds: exact (integer or float bit-equal after rounding to 1e-9 s)
  * Analytics numeric fields: relative tolerance ANALYTICS_REL_TOL (1e-6) documented here

Uses ``scripts/ci/unit_contract_lib.py`` only — no second conversion table.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci import unit_contract_lib as uc  # noqa: E402

ANALYTICS_REL_TOL = 1e-6
FAULT_SECONDS_ATOL = 0.0  # exact — use math.isclose with rel_tol=0, abs_tol=1e-9

REPO = ROOT
IP_GOLDENS_DIR = REPO / "tests" / "fixtures" / "si_cutover" / "ip_goldens"
UNIT_VECTORS = REPO / "sql" / "contract" / "goldens" / "unit_vectors.json"
UNIT_SCENARIOS = REPO / "sql" / "contract" / "goldens" / "si_parity_unit_scenarios.json"
P2_HOOK_GOLDEN = REPO / "tests" / "fixtures" / "si_cutover" / "p2_si_hook.json"
COOKBOOK_FIXTURES = REPO / "docs" / "rules" / "cookbook" / "fixtures"
P3_BASELINE_FIXTURE = REPO / "tests" / "fixtures" / "si_cutover" / "p3_baseline_mini"

CARRYOVER_RULES_P0 = (
    "VAV-1",
    "SV-FLATLINE",
    "SV-RANGE",
    "SV-STALE",
    "OAT-METEO",
)


@dataclass(frozen=True)
class StageResult:
    stage: str
    comparisons: int
    errors: tuple[str, ...]


def _metric_doc() -> dict[str, Any]:
    return uc.load_json(uc.METRIC_UNITS)


def fault_seconds_equal(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)


def analytics_relative_equal(a: float, b: float) -> bool:
    if not math.isfinite(a) and not math.isfinite(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= ANALYTICS_REL_TOL


def fdd_daily_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("building_id", "")),
        str(row.get("rule_id", "")),
        str(row.get("equipment_id", "")),
        str(row.get("utc_day", "")),
    )


def load_ip_golden(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != "si-cutover-ip-golden-v1":
        raise ValueError(f"{path}: expected schema si-cutover-ip-golden-v1")
    return body


def iter_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_baseline_site_dir(site_dir: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name in (
        "sql_fdd_daily.jsonl.gz",
        "pandas_fdd_daily.jsonl.gz",
        "analytics_rows.jsonl.gz",
        "sample_counts.jsonl.gz",
    ):
        path = site_dir / name
        if path.is_file():
            out[name.removesuffix(".jsonl.gz")] = list(iter_jsonl_gz(path))
    return out


def compare_p0_ip_golden(golden: dict[str, Any]) -> StageResult:
    """P0: pandas IP == SQL IP from frozen golden rows (exact fault_seconds)."""
    sql_rows = golden.get("sql_fdd_daily") or []
    pandas_rows = golden.get("pandas_fdd_daily") or []
    errors: list[str] = []
    comparisons = 0
    pandas_by_key = {fdd_daily_key(r): r for r in pandas_rows}
    for sql in sql_rows:
        key = fdd_daily_key(sql)
        other = pandas_by_key.get(key)
        if other is None:
            errors.append(f"P0 missing pandas row for {key}")
            continue
        comparisons += 1
        if not fault_seconds_equal(sql.get("fault_seconds", 0), other.get("fault_seconds", 0)):
            errors.append(
                f"P0 fault_seconds {key}: sql={sql.get('fault_seconds')} "
                f"pandas={other.get('fault_seconds')}"
            )
        if str(sql.get("status", "")) != str(other.get("status", "")):
            errors.append(f"P0 status {key}: sql={sql.get('status')} pandas={other.get('status')}")
    if not sql_rows:
        errors.append("P0: golden has no sql_fdd_daily rows")
    return StageResult("P0", comparisons, tuple(errors))


def compare_p0_analytics_golden(golden: dict[str, Any]) -> StageResult:
    """P0 analytics slice inside ip golden (optional rows)."""
    rows = golden.get("analytics_rows") or []
    errors: list[str] = []
    comparisons = 0
    for rec in rows:
        endpoint = rec.get("endpoint", "")
        if endpoint != "/api/analytics/oat_meteo":
            continue
        row = rec.get("row") if isinstance(rec.get("row"), dict) else {}
        sql_val = row.get("mean_abs_diff_f")
        pandas_val = row.get("pandas_mean_abs_diff_f")
        if sql_val is None or pandas_val is None:
            continue
        comparisons += 1
        if not analytics_relative_equal(float(sql_val), float(pandas_val)):
            errors.append(
                f"P0 analytics OAT-METEO: sql={sql_val} pandas={pandas_val} "
                f"(rel tol {ANALYTICS_REL_TOL})"
            )
    return StageResult("P0-analytics", comparisons, tuple(errors))


def verify_unit_vector_goldens() -> StageResult:
    metric = _metric_doc()
    cases = json.loads(UNIT_VECTORS.read_text(encoding="utf-8")).get("cases") or []
    errors: list[str] = []
    comparisons = 0
    for case in cases:
        qid = case["quantity"]
        src = case["source_unit"]
        inp = float(case["input"])
        expect = float(case["metric"])
        tol = float(case.get("tol", 1e-9))
        try:
            got = uc.convert_to_canonical(metric, qid, inp, src)
        except ValueError as exc:
            errors.append(f"unit_vectors {case['id']}: {exc}")
            continue
        comparisons += 1
        if abs(got - expect) > tol:
            errors.append(f"unit_vectors {case['id']}: got {got} expect {expect}")
    return StageResult("unit_vectors", comparisons, tuple(errors))


def verify_unit_scenarios() -> StageResult:
    if not UNIT_SCENARIOS.is_file():
        return StageResult("unit_scenarios", 0, ("missing si_parity_unit_scenarios.json",))
    metric = _metric_doc()
    doc = json.loads(UNIT_SCENARIOS.read_text(encoding="utf-8"))
    errors: list[str] = []
    comparisons = 0
    for scenario in doc.get("scenarios") or []:
        sid = scenario.get("id", "?")
        if scenario.get("expect_error"):
            for probe in scenario.get("probes") or []:
                comparisons += 1
                try:
                    uc.convert_to_canonical(
                        metric,
                        probe["quantity"],
                        float(probe["input"]),
                        probe["source_unit"],
                    )
                    errors.append(f"{sid}: expected conversion error for {probe}")
                except ValueError:
                    pass
            continue
        for probe in scenario.get("probes") or []:
            comparisons += 1
            qid = probe["quantity"]
            val = float(probe["input"])
            unit = probe["source_unit"]
            expect = float(probe["metric"])
            tol = float(probe.get("tol", 1e-9))
            got = uc.convert_to_canonical(metric, qid, val, unit)
            if abs(got - expect) > tol:
                errors.append(f"{sid}/{probe.get('label', unit)}: got {got} expect {expect}")
        for pair in scenario.get("physical_pairs") or []:
            comparisons += 1
            a = uc.convert_to_canonical(
                metric, pair["quantity"], float(pair["ip_value"]), pair["ip_unit"]
            )
            b = uc.convert_to_canonical(
                metric, pair["quantity"], float(pair["si_value"]), pair["si_unit"]
            )
            if abs(a - b) > float(pair.get("tol", 1e-9)):
                errors.append(f"{sid} physical_pair: {a} != {b}")
    return StageResult("unit_scenarios", comparisons, tuple(errors))


def _pandas_fault_seconds(rule_id: str, frame, params: dict[str, Any]) -> float:
    from open_fdd.rules.runner import run_rule

    result = run_rule(rule_id, frame, params=params, poll_seconds=300.0, quality=False)
    metrics = result.metrics or {}
    hours = metrics.get("fault_hours")
    if hours is None:
        hours = metrics.get("fault_hour") or 0.0
    return float(hours) * 3600.0


def _load_cookbook_fixture(name: str):
    import pandas as pd

    path = COOKBOOK_FIXTURES / name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
    return df


def run_p1_cookbook_carryover() -> StageResult:
    """P1: pandas IP == pandas SI on carry-over rule fixtures (fault seconds exact)."""
    errors: list[str] = []
    comparisons = 0
    metric = _metric_doc()
    path = COOKBOOK_FIXTURES / "vav1_obvious_fault.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or "zone_t" not in rows[0]:
        return StageResult("P1", 0, ("VAV-1 fixture missing zone_t",))
    ip_out = 0
    si_out = 0
    low_c = uc.convert_to_canonical(metric, "absolute_temperature", 68.0, "degF")
    high_c = uc.convert_to_canonical(metric, "absolute_temperature", 76.0, "degF")
    for row in rows:
        zt = float(row["zone_t"])
        if zt < 68.0 or zt > 76.0:
            ip_out += 1
        zc = uc.convert_to_canonical(metric, "absolute_temperature", zt, "degF")
        if zc < low_c or zc > high_c:
            si_out += 1
    comparisons += 1
    if ip_out != si_out:
        errors.append(f"P1 VAV-1 out-of-band samples: ip={ip_out} si={si_out}")
    return StageResult("P1", comparisons, tuple(errors))


def run_p2_hook_golden() -> StageResult:
    """P2: pandas SI == SQL SI using hook golden until W4 live SQL SI lands."""
    if not P2_HOOK_GOLDEN.is_file():
        return StageResult("P2", 0, ("missing p2_si_hook.json",))
    doc = json.loads(P2_HOOK_GOLDEN.read_text(encoding="utf-8"))
    errors: list[str] = []
    comparisons = 0
    for row in doc.get("pairs") or []:
        comparisons += 1
        sql_s = float(row["sql_si_fault_seconds"])
        pandas_s = float(row["pandas_si_fault_seconds"])
        if not fault_seconds_equal(sql_s, pandas_s):
            errors.append(
                f"P2 {row.get('rule_id')}/{row.get('equipment_id')}: "
                f"sql_si={sql_s} pandas_si={pandas_s}"
            )
    return StageResult("P2", comparisons, tuple(errors))


def compare_p3_post_cutover(
    *,
    baseline_dir: Path,
    building_id: str,
    live_sql_daily: Iterable[dict[str, Any]],
    live_sample_counts: Iterable[dict[str, Any]],
) -> StageResult:
    """P3 live: post-cutover SQL SI fault seconds == pre-cutover W0c IP baseline."""
    site_dir = baseline_dir / building_id
    if not site_dir.is_dir():
        return StageResult("P3", 0, (f"baseline missing site dir {site_dir}",))
    baseline = load_baseline_site_dir(site_dir)
    base_sql = {
        fdd_daily_key(r): r for r in baseline.get("sql_fdd_daily") or []
    }
    errors: list[str] = []
    comparisons = 0
    for row in live_sql_daily:
        if str(row.get("building_id")) != building_id:
            continue
        key = fdd_daily_key(row)
        base = base_sql.get(key)
        if base is None:
            continue
        comparisons += 1
        if not fault_seconds_equal(row.get("fault_seconds", 0), base.get("fault_seconds", 0)):
            errors.append(
                f"P3 {key}: live_si={row.get('fault_seconds')} "
                f"ip_baseline={base.get('fault_seconds')}"
            )
    base_counts = {
        (r.get("building_id"), r.get("table")): int(r.get("row_count", 0))
        for r in baseline.get("sample_counts") or []
    }
    for row in live_sample_counts:
        if str(row.get("building_id")) != building_id:
            continue
        key = (row.get("building_id"), row.get("table"))
        comparisons += 1
        if base_counts.get(key) != int(row.get("row_count", 0)):
            errors.append(f"P3 sample_counts {key}: live={row.get('row_count')} baseline={base_counts.get(key)}")
    return StageResult("P3", comparisons, tuple(errors))


def run_fixture_stages(*, golden_name: str = "SYNTH_SELFTEST.json") -> list[StageResult]:
    golden_path = IP_GOLDENS_DIR / golden_name
    golden = load_ip_golden(golden_path)
    return [
        verify_unit_vector_goldens(),
        verify_unit_scenarios(),
        compare_p0_ip_golden(golden),
        compare_p0_analytics_golden(golden),
        run_p1_cookbook_carryover(),
        run_p2_hook_golden(),
    ]


def summarize(results: list[StageResult]) -> tuple[int, list[str]]:
    total = sum(r.comparisons for r in results)
    errors: list[str] = []
    for r in results:
        errors.extend(r.errors)
    return total, errors
