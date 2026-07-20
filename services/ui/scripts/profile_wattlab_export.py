#!/usr/bin/env python3
"""Deterministic WattLab export size/timing profiler.

Builds a fixed multi-equipment fixture and writes comparable JSON metrics.

Modes
-----
``live`` (default)
    Measure whatever ``export_agent_bundle`` does *now* (post-profile default
    is ``summary``). This is **not** a frozen legacy baseline.

``summary`` / ``diagnostic`` / ``forensic``
    Explicitly pass that export profile.

Frozen pre-change Cartesian metrics live in the checked-in fixture
``tests/fixtures/wattlab_export_before.json``. Optionally re-measure a local
copy under ``.artifacts/wattlab_export_before.json`` for Task 5 comparisons
(``--baseline``); do not treat ``--mode live`` as that baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_api import AgentDataset, AgentRun, export_agent_bundle  # noqa: E402
from app.rules.base import RuleResult  # noqa: E402

# Portable aggregate-only before metrics (checked in). Local re-measure for Task 5.
CHECKED_IN_BASELINE_PATH = ROOT / "tests" / "fixtures" / "wattlab_export_before.json"
LOCAL_ARTIFACT_BASELINE_PATH = ROOT / ".artifacts" / "wattlab_export_before.json"

# ``current`` is a deprecated alias for ``live`` (kept so old docs/scripts still run).
_LIVE_ALIASES = frozenset({"live", "current"})
_PROFILE_MODES = frozenset({"summary", "diagnostic", "forensic"})


def load_before_baseline(path: Path | str | None = None) -> dict[str, Any]:
    """Load frozen pre-change aggregate metrics (checked-in fixture by default)."""
    baseline = Path(path) if path is not None else CHECKED_IN_BASELINE_PATH
    return json.loads(baseline.read_text(encoding="utf-8"))


def resolve_before_baseline_path() -> Path:
    """Prefer local measured artifact when present; else checked-in fixture."""
    if LOCAL_ARTIFACT_BASELINE_PATH.is_file():
        return LOCAL_ARTIFACT_BASELINE_PATH
    return CHECKED_IN_BASELINE_PATH


def _idx(periods: int = 24) -> pd.DatetimeIndex:
    return pd.date_range("2024-06-01", periods=periods, freq="1h", tz="UTC")


def build_profile_fixture() -> tuple[AgentDataset, AgentRun]:
    """CHW plant, DX AHU, chilled-water AHU, heat pump, VAV + mixed FDD statuses."""
    idx = _idx()
    n = len(idx)

    chw = pd.DataFrame(
        {
            "chiller-status": [1] * (n // 2) + [0] * (n - n // 2),
            "leaving-water-temp": [44.0 + (i % 3) for i in range(n)],
            "outside-air-temp": [70.0 + (i % 5) for i in range(n)],
        },
        index=idx,
    )
    chw.attrs["equipment_type"] = "CHW_PLANT"

    dx = pd.DataFrame(
        {
            "discharge-air-temp": [55.0 + (i % 4) for i in range(n)],
            "fan-status": [1] * n,
            "compressor-status": [1, 0] * (n // 2),
            "outside-air-temp": [72.0] * n,
            "cooling-cmd": [40.0] * n,
        },
        index=idx,
    )
    dx.attrs["equipment_type"] = "AHU"

    chw_ahu = pd.DataFrame(
        {
            "discharge-air-temp": [58.0] * n,
            "fan-status": [1] * n,
            "cooling-valve": [30.0] * n,
            "outside-air-temp": [68.0] * n,
        },
        index=idx,
    )
    chw_ahu.attrs["equipment_type"] = "AHU"

    hp = pd.DataFrame(
        {
            "discharge-air-temp": [60.0] * n,
            "fan-status": [1] * n,
            "compressor-status": [0] * n,
            "heat-pump-mode": ["cool"] * n,
            "outside-air-temp": [75.0] * n,
        },
        index=idx,
    )
    hp.attrs["equipment_type"] = "HEAT_PUMP"

    vav = pd.DataFrame(
        {
            "zone-air-temp": [72.0 + (i % 2) for i in range(n)],
            "zone-air-temp-sp": [72.0] * n,
            "damper-cmd": [50.0] * n,
            "airflow": [400.0] * n,
        },
        index=idx,
    )
    vav.attrs["equipment_type"] = "VAV"

    frames = {
        "CHW_PLANT_1": chw,
        "AHU_DX_1": dx,
        "AHU_CHW_1": chw_ahu,
        "HP_1": hp,
        "VAV_1": vav,
    }
    role_map = {
        "CHW_PLANT_1": {
            "chiller-status": "chiller-status",
            "leaving-water-temp": "leaving-water-temp",
            "outside-air-temp": "outside-air-temp",
            "equipment_type": "CHW_PLANT",
        },
        "AHU_DX_1": {
            "discharge-air-temp": "discharge-air-temp",
            "fan-status": "fan-status",
            "compressor-status": "compressor-status",
            "outside-air-temp": "outside-air-temp",
            "cooling-cmd": "cooling-cmd",
            "equipment_type": "AHU",
            "cooling_technology": "dx",
        },
        "AHU_CHW_1": {
            "discharge-air-temp": "discharge-air-temp",
            "fan-status": "fan-status",
            "cooling-valve": "cooling-valve",
            "outside-air-temp": "outside-air-temp",
            "equipment_type": "AHU",
            "cooling_technology": "chw",
        },
        "HP_1": {
            "discharge-air-temp": "discharge-air-temp",
            "fan-status": "fan-status",
            "compressor-status": "compressor-status",
            "heat-pump-mode": "heat-pump-mode",
            "outside-air-temp": "outside-air-temp",
            "equipment_type": "HEAT_PUMP",
        },
        "VAV_1": {
            "zone-air-temp": "zone-air-temp",
            "zone-air-temp-sp": "zone-air-temp-sp",
            "damper-cmd": "damper-cmd",
            "airflow": "airflow",
            "equipment_type": "VAV",
        },
    }

    weather = pd.DataFrame(
        {
            "web-outside-air-temp": [70.0 + (i % 6) for i in range(n)],
            "web-outside-air-humidity": [45.0] * n,
        },
        index=idx,
    )

    dataset = AgentDataset(
        building_id="PROFILE_FIXTURE",
        frames=frames,
        weather=weather,
        role_map=role_map,
        params={},
        unit_system="imperial",
        prefer_web_oat=True,
        source_path="profile_fixture",
        package_report={"package_health": {"grade": "ok", "summary_lines": []}},
    )

    fault_mask = pd.Series([False, True, True, False] * (n // 4), index=idx)
    results = [
        RuleResult(
            rule_id="FC1",
            equipment_id="AHU_DX_1",
            status="FAULT",
            applicable=True,
            equipment_type="AHU",
            fault_hours=2.0,
            fault_pct=25.0,
            fault_sample_count=2,
            sample_count=n,
            raw_fault=fault_mask,
            confirmed_fault=fault_mask,
            plot_series={"discharge-air-temp": dx["discharge-air-temp"]},
        ),
        RuleResult(
            rule_id="FC2",
            equipment_id="AHU_CHW_1",
            status="PASS",
            applicable=True,
            equipment_type="AHU",
            fault_hours=0.0,
            fault_pct=0.0,
            sample_count=n,
            raw_fault=pd.Series(False, index=idx),
            confirmed_fault=pd.Series(False, index=idx),
            plot_series={"discharge-air-temp": chw_ahu["discharge-air-temp"]},
        ),
        RuleResult(
            rule_id="FC3",
            equipment_id="HP_1",
            status="ERROR",
            applicable=True,
            equipment_type="HEAT_PUMP",
            notes="simulated error",
            sample_count=n,
            plot_series={"discharge-air-temp": hp["discharge-air-temp"]},
        ),
        RuleResult(
            rule_id="FC4",
            equipment_id="VAV_1",
            status="SKIPPED_MISSING_ROLES",
            applicable=False,
            equipment_type="VAV",
            missing_roles=["fan-status"],
            sample_count=n,
        ),
        RuleResult(
            rule_id="FC5",
            equipment_id="CHW_PLANT_1",
            status="SKIPPED_EQUIPMENT_OFF",
            applicable=False,
            equipment_type="CHW_PLANT",
            sample_count=n,
        ),
        RuleResult(
            rule_id="FC6",
            equipment_id="VAV_1",
            status="NOT_APPLICABLE_EQUIPMENT_TYPE",
            applicable=False,
            equipment_type="VAV",
            sample_count=n,
        ),
    ]
    status_counts = dict(Counter(r.status for r in results))
    run = AgentRun(
        results=results,
        status_counts=status_counts,
        params={},
        meta={"result_count": len(results), "fixture": "wattlab_export_profile"},
    )
    return dataset, run


def resolve_suppressed_combinations(
    manifest: dict[str, Any] | None,
    *,
    results: list[Any] | None = None,
) -> int:
    """Resolve suppressed evidence count without treating an explicit 0 as missing.

    Prefer ``files_suppressed`` when the key is present (including 0). Otherwise
    fall back to ``export_counts.suppressed_status`` totals, then to counting
    ``NEVER_TIMESERIES_STATUSES`` on ``results``.
    """
    if isinstance(manifest, dict) and "files_suppressed" in manifest:
        try:
            return int(manifest["files_suppressed"])
        except (TypeError, ValueError):
            pass
    if isinstance(manifest, dict):
        ec = manifest.get("export_counts") or {}
        suppressed_status = ec.get("suppressed_status")
        if isinstance(suppressed_status, dict) and suppressed_status:
            return int(sum(int(v) for v in suppressed_status.values()))
    if results:
        from app.wattlab_dump import NEVER_TIMESERIES_STATUSES

        return sum(1 for r in results if getattr(r, "status", None) in NEVER_TIMESERIES_STATUSES)
    return 0


def _dir_uncompressed_bytes(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _zip_bytes(root: Path) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(root).as_posix())
    return buf.getvalue()


def measure_export(
    *,
    mode: str = "live",
    profile: str | None = None,
) -> dict[str, Any]:
    """Export the fixed fixture and return comparable metrics.

    ``mode="live"`` (alias ``current``) measures the active default export path
    — not the frozen pre-change baseline fixture.
    """
    normalized = "live" if mode in _LIVE_ALIASES else mode
    dataset, run = build_profile_fixture()
    with tempfile.TemporaryDirectory(prefix="wattlab_profile_") as td:
        out = Path(td)
        t0 = time.perf_counter()
        if normalized in _PROFILE_MODES:
            export_profile = profile or normalized
        else:
            # live: use export_agent_bundle default (summary) unless overridden
            export_profile = profile
        if export_profile is not None:
            written = export_agent_bundle(
                dataset, run, out, include_bootstrap=False, profile=export_profile
            )
            reported_profile = export_profile
        else:
            written = export_agent_bundle(dataset, run, out, include_bootstrap=False)
            reported_profile = "summary"  # live default after Task 4
        elapsed = time.perf_counter() - t0

        ts_dir = out / "fdd_timeseries"
        per_rule = len(list(ts_dir.glob("*.csv"))) if ts_dir.is_dir() else 0
        file_count = sum(1 for p in out.rglob("*") if p.is_file())
        uncompressed = _dir_uncompressed_bytes(out)
        compressed = len(_zip_bytes(out))
        status_counts = dict(Counter(r.status for r in (run.results or [])))
        suppressed = 0
        manifest_path = out / "MANIFEST.json"
        man: dict[str, Any] | None = None
        if manifest_path.is_file():
            try:
                man = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                man = None
        suppressed = resolve_suppressed_combinations(man, results=list(run.results or []))

        return {
            "mode": normalized,
            "profile": reported_profile,
            "elapsed_seconds": round(elapsed, 6),
            "file_count": file_count,
            "compressed_bytes": compressed,
            "uncompressed_bytes": uncompressed,
            "result_status_counts": status_counts,
            "per_rule_timeseries_count": per_rule,
            "suppressed_combinations": suppressed,
            "artifact_keys": sorted(str(k) for k in written),
            "baseline_note": (
                "live measures active export_agent_bundle; frozen before-metrics are "
                f"{CHECKED_IN_BASELINE_PATH.as_posix()}"
            ),
            "metrics_note": (
                "file_count/compressed_bytes/uncompressed_bytes are whole-directory "
                "profiler measurements of the final export (including MANIFEST). "
                "MANIFEST payload_* fields exclude MANIFEST self-bytes."
            ),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Profile WattLab export size/timing. "
            "'live' measures the active export path (not the frozen pre-change baseline)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("live", "current", "summary", "diagnostic", "forensic"),
        default="live",
        help=(
            "live=measure active export_agent_bundle default (alias: current, deprecated); "
            "summary/diagnostic/forensic=explicit profile. "
            "Frozen before-metrics: tests/fixtures/wattlab_export_before.json"
        ),
    )
    parser.add_argument("--out", type=str, required=True, help="JSON output path")
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help=(
            "Optional before-JSON for before/after comparison (Task 5). "
            "Defaults are not applied; pass the checked-in fixture or "
            ".artifacts/wattlab_export_before.json explicitly."
        ),
    )
    args = parser.parse_args(argv)

    metrics = measure_export(mode=args.mode)
    payload: dict[str, Any] = metrics
    if args.baseline:
        baseline_path = Path(args.baseline)
        before = load_before_baseline(baseline_path)
        payload = {
            "runtime_seconds": {
                "before": before.get("elapsed_seconds"),
                "after": metrics["elapsed_seconds"],
            },
            "file_count": {"before": before.get("file_count"), "after": metrics["file_count"]},
            "compressed_bytes": {
                "before": before.get("compressed_bytes"),
                "after": metrics["compressed_bytes"],
            },
            "uncompressed_bytes": {
                "before": before.get("uncompressed_bytes"),
                "after": metrics["uncompressed_bytes"],
            },
            "per_rule_timeseries": {
                "before": before.get("per_rule_timeseries_count"),
                "after": metrics["per_rule_timeseries_count"],
            },
            "suppressed_combinations": int(metrics.get("suppressed_combinations") or 0),
            "before_path": str(baseline_path),
            "before": before,
            "after": metrics,
        }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
