"""Thin IPMVP Option C–style monthly M&V twin (oracle for Wave S4 SQL compare).

Product surface is **2P only** (``energy = intercept + slope * degree_days``) to
match ``POST /api/analytics/mv``. Full 3P/4P/5P + G14 live in
``open_fdd.ecm_engineering.changepoint`` (Wave S3) — this module does not reinvent
Camber; it twins the thin central OLS path for qualification.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

QV_MV_CHANGE_POINT = "mv-change-point-v1"


def _round4(x: float) -> float:
    return round(float(x) * 10_000.0) / 10_000.0


def _round6(x: float) -> float:
    return round(float(x) * 1_000_000.0) / 1_000_000.0


def ols_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float] | None:
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if x is not None and y is not None and float(x) == float(x) and float(y) == float(y)
    ]
    n = len(pairs)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in pairs) / n
    mean_y = sum(y for _, y in pairs) / n
    ss_xx = ss_xy = ss_yy = 0.0
    for x, y in pairs:
        dx = x - mean_x
        dy = y - mean_y
        ss_xx += dx * dx
        ss_xy += dx * dy
        ss_yy += dy * dy
    if ss_xx < 1e-12:
        return None
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in pairs)
    r2 = (1.0 - ss_res / ss_yy) if ss_yy > 0.0 else float("nan")
    return slope, intercept, r2


def split_periods(
    periods: Sequence[str],
    *,
    baseline_periods: Sequence[str] | None = None,
    reporting_periods: Sequence[str] | None = None,
    baseline_end: str | None = None,
) -> tuple[set[str], set[str], list[str]]:
    warnings: list[str] = []
    if baseline_periods is not None and reporting_periods is not None:
        return set(baseline_periods), set(reporting_periods), warnings
    if baseline_end is not None:
        base = {p for p in periods if p <= baseline_end}
        rep = {p for p in periods if p > baseline_end}
        if not base or not rep:
            warnings.append(f"baseline_end={baseline_end} left empty baseline or reporting set")
        return base, rep, warnings
    sorted_p = sorted(periods)
    if len(sorted_p) < 4:
        warnings.append(f"auto split needs ≥4 months, got {len(sorted_p)}; put all in baseline")
        return set(sorted_p), set(), warnings
    mid = len(sorted_p) // 2
    base = set(sorted_p[:mid])
    rep = set(sorted_p[mid:])
    warnings.append(
        f"auto-split periods: baseline n={len(base)} reporting n={len(rep)} "
        "(set baseline_end or lists for IPMVP control)"
    )
    return base, rep, warnings


def change_point_monthly(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline: Iterable[str],
    reporting: Iterable[str],
    dd_kind: str = "degree_days",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    base_set = set(baseline)
    rep_set = set(reporting)
    warnings: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    for r in rows:
        period = str(r.get("period") or r.get("month") or "")
        if period not in base_set:
            continue
        energy = r.get("energy", r.get("kwh", r.get("usage")))
        dd = r.get("degree_days", r.get("dd", r.get("hdd", r.get("cdd"))))
        try:
            e = float(energy)
            d = float(dd)
        except (TypeError, ValueError):
            continue
        if e != e or d != d:
            continue
        xs.append(d)
        ys.append(e)
    if len(xs) < 2:
        warnings.append(f"need ≥2 finite baseline months for OLS, got {len(xs)}")
        out = []
        for r in rows:
            period = str(r.get("period") or r.get("month") or "")
            kind = (
                "baseline"
                if period in base_set
                else "reporting"
                if period in rep_set
                else "other"
            )
            energy = float(r.get("energy", r.get("kwh", r.get("usage")) or 0.0))
            dd = float(r.get("degree_days", r.get("dd", r.get("hdd", r.get("cdd"))) or 0.0))
            out.append(
                {
                    "period": period,
                    "energy": _round4(energy),
                    "degree_days": _round4(dd),
                    "period_kind": kind,
                    "predicted": None,
                    "savings": None,
                    "meter_id": r.get("meter_id"),
                }
            )
        return None, out, warnings
    if len(xs) < 6:
        warnings.append(f"baseline n={len(xs)} <6 — fit is provisional (IPMVP often wants ≥12)")
    fit_t = ols_fit(xs, ys)
    if fit_t is None:
        warnings.append("OLS fit failed (degenerate degree-days)")
        return None, [], warnings
    slope, intercept, r2 = fit_t
    fit = {
        "intercept": _round4(intercept),
        "slope": _round6(slope),
        "r2": _round4(r2),
        "n_baseline": len(xs),
        "dd_kind": dd_kind,
    }
    out = []
    for r in rows:
        period = str(r.get("period") or r.get("month") or "")
        kind = (
            "baseline"
            if period in base_set
            else "reporting"
            if period in rep_set
            else "other"
        )
        energy = float(r.get("energy", r.get("kwh", r.get("usage")) or 0.0))
        dd = float(r.get("degree_days", r.get("dd", r.get("hdd", r.get("cdd"))) or 0.0))
        predicted = savings = None
        if kind in ("reporting", "baseline") and dd == dd:
            pred = intercept + slope * dd
            predicted = _round4(pred)
            savings = _round4(pred - energy)
        out.append(
            {
                "period": period,
                "energy": _round4(energy),
                "degree_days": _round4(dd),
                "period_kind": kind,
                "predicted": predicted,
                "savings": savings,
                "meter_id": r.get("meter_id"),
            }
        )
    return fit, out, warnings


def handle_series(series: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build an analytics-like envelope from series payload (oracle twin)."""
    warnings: list[str] = []
    if isinstance(series, Sequence) and not isinstance(series, (str, bytes)):
        rows_raw: list[Mapping[str, Any]] = list(series)  # type: ignore[arg-type]
        meta: Mapping[str, Any] = {}
    else:
        meta = series  # type: ignore[assignment]
        raw = meta.get("rows") or meta.get("points") or []
        rows_raw = list(raw) if isinstance(raw, Sequence) else []

    periods = [str(r.get("period") or r.get("month") or "") for r in rows_raw]
    base, rep, split_warns = split_periods(
        periods,
        baseline_periods=meta.get("baseline_periods") if meta else None,
        reporting_periods=meta.get("reporting_periods") if meta else None,
        baseline_end=meta.get("baseline_end") if meta else None,
    )
    warnings.extend(split_warns)
    dd_kind = str((meta or {}).get("dd_kind") or "degree_days")
    fit, rows, compute_warns = change_point_monthly(
        rows_raw, baseline=base, reporting=rep, dd_kind=dd_kind
    )
    warnings.extend(compute_warns)
    warnings.append(
        "mv-change-point-v1: IPMVP Option C–style monthly OLS twin (not investment-grade Camber)"
    )
    savings_reporting = sum(
        float(r["savings"])
        for r in rows
        if r.get("period_kind") == "reporting" and r.get("savings") is not None
    )
    reporting_energy = sum(
        float(r["energy"]) for r in rows if r.get("period_kind") == "reporting"
    )
    predicted_reporting = sum(
        float(r["predicted"])
        for r in rows
        if r.get("period_kind") == "reporting" and r.get("predicted") is not None
    )
    return {
        "schema_version": "analytics-envelope-v1",
        "query_version": QV_MV_CHANGE_POINT,
        "engine": "open_fdd.analytics.mv_change_point",
        "rows": rows,
        "warnings": warnings,
        "coverage": {
            "method": "ipmvp_option_c_monthly_dd_ols",
            "dd_kind": dd_kind,
            "n_rows": len(rows),
            "n_baseline": len(base),
            "n_reporting": len(rep),
            "fit": fit,
            "savings_reporting_total": _round4(savings_reporting),
            "reporting_energy_total": _round4(reporting_energy),
            "predicted_reporting_total": _round4(predicted_reporting),
        },
    }


def demo_seed_series() -> dict[str, Any]:
    """Deterministic seed shared with Rust unit tests / qualification gate."""
    base = []
    for period, dd in [
        ("2023-01", 800.0),
        ("2023-02", 700.0),
        ("2023-03", 500.0),
        ("2023-04", 300.0),
        ("2023-05", 100.0),
        ("2023-06", 50.0),
        ("2023-07", 20.0),
        ("2023-08", 30.0),
        ("2023-09", 80.0),
        ("2023-10", 250.0),
        ("2023-11", 450.0),
        ("2023-12", 750.0),
    ]:
        base.append({"period": period, "energy": 500.0 + 2.0 * dd, "degree_days": dd})
    rep = []
    for period, dd in [
        ("2024-01", 780.0),
        ("2024-02", 690.0),
        ("2024-03", 480.0),
    ]:
        rep.append(
            {"period": period, "energy": 500.0 + 2.0 * dd - 100.0, "degree_days": dd}
        )
    return {
        "rows": base + rep,
        "baseline_end": "2023-12",
        "dd_kind": "hdd",
    }
