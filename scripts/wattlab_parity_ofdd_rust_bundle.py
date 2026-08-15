#!/usr/bin/env python3
"""Assemble a DataFusion Engineering Bundle from Rust JWT APIs.

Does NOT enable OPENFDD_WATTLAB_PYTHON_EXPORT / pandas tools/wattlab_export.
Writes the same filenames as the Vibe19 openfdd_engineering_bundle_v1 dump so
wattlab_parity_diff.py can compare dump-to-dump.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wattlab_parity_ofdd_rust_capture import (  # noqa: E402
    DEFAULT_BASE,
    DEFAULT_SCHED,
    DEFAULT_SESSION,
    _req,
    _write_json,
    login,
    main as capture_main,
)

DEFAULT_CAPTURE = ROOT / "reports/wattlab-parity/artifacts/ofdd_rust"
DEFAULT_BUNDLE = ROOT / "reports/wattlab-parity/artifacts/ofdd_rust_bundle"

_RULE_ALIASES = {"FC13-SAT-HIGH": "FC13"}

EXTRA_ANALYTICS = (
    ("mechanical_cooling", "/api/analytics/mechanical-cooling"),
    ("economizer", "/api/analytics/economizer"),
    ("bas_vs_web_oat", "/api/analytics/bas-vs-web-oat"),
    ("metering", "/api/analytics/metering"),
    ("fuel", "/api/analytics/fuel"),
    ("rcx_ahu", "/api/analytics/rcx/ahu"),
    ("rcx_vav", "/api/analytics/rcx/vav"),
    ("rcx_chiller", "/api/analytics/rcx/chiller"),
    ("rcx_boiler", "/api/analytics/rcx/boiler"),
    ("rcx_preset", "/api/analytics/rcx/preset"),
    ("setpoints", "/api/analytics/setpoints"),
    ("diurnal", "/api/analytics/diurnal"),
    ("topology", "/api/analytics/topology"),
    ("sensor_stats_all", "/api/analytics/sensor-stats"),
    ("vav_health", "/api/analytics/vav-health"),
)


def _unwrap(raw):
    if isinstance(raw, dict) and "body" in raw and "status" in raw:
        return raw.get("status"), raw.get("body")
    return 200, raw


def _analytics(body) -> dict:
    if not isinstance(body, dict):
        return {}
    if isinstance(body.get("analytics"), dict):
        return body["analytics"]
    return body


def _rows_of(body) -> list:
    env = _analytics(body)
    for key in ("rows", "equipment", "results", "points"):
        val = env.get(key)
        if isinstance(val, list) and val:
            return val
    return []


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    names = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=names, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in names})


def _load(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def assemble(capture_dir: Path, bundle_dir: Path) -> dict:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    missing_apis: list[str] = []
    written: list[str] = []

    def mark(name: str) -> None:
        written.append(name)

    health = _load(capture_dir / "health.json") or {}
    _, health_body = _unwrap(health) if isinstance(health, dict) else (None, health)
    version = None
    if isinstance(health_body, dict):
        version = health_body.get("version")

    fdd_wrap = _load(capture_dir / "fdd_results.json") or {}
    _, fdd_body = _unwrap(fdd_wrap)
    rust_rows = []
    if isinstance(fdd_body, dict):
        rust_rows = fdd_body.get("results") or []
    if not isinstance(rust_rows, list):
        rust_rows = []

    findings = []
    for r in rust_rows:
        if not isinstance(r, dict):
            continue
        rid = _RULE_ALIASES.get(str(r.get("rule_id") or ""), str(r.get("rule_id") or ""))
        findings.append(
            {
                "rule_id": rid,
                "equipment_id": r.get("equipment_id") or "",
                "equipment_type": r.get("equipment_type") or "",
                "status": r.get("status") or "",
                "applicable": str(r.get("status") or "").upper()
                not in {
                    "NOT_APPLICABLE_EQUIPMENT_TYPE",
                    "NOT_APPLICABLE",
                    "SKIPPED_MISSING_ROLES",
                    "SKIPPED_EQUIPMENT_OFF",
                },
                "confirmed_fault": str(r.get("status") or "").upper() == "FAULT",
                "fault_hours": r.get("fault_hours") if r.get("fault_hours") is not None else 0.0,
                "fault_pct": r.get("fault_pct") if r.get("fault_pct") is not None else "",
                "fault_samples": "",
                "sample_count": "",
                "missing_roles": json.dumps(r.get("missing_roles") or []),
                "notes": r.get("notes") or "",
                "title": r.get("title") or "",
            }
        )
    _write_csv(
        bundle_dir / "fdd_findings.csv",
        findings,
        [
            "rule_id",
            "equipment_id",
            "equipment_type",
            "status",
            "applicable",
            "confirmed_fault",
            "fault_hours",
            "fault_pct",
            "fault_samples",
            "sample_count",
            "missing_roles",
            "notes",
            "title",
        ],
    )
    mark("fdd_findings.csv")

    summary_map: dict[str, dict] = {}
    for row in findings:
        rid = row["rule_id"]
        rec = summary_map.setdefault(
            rid,
            {
                "rule_id": rid,
                "title": row.get("title") or "",
                "fault_count": 0,
                "pass_count": 0,
                "skip_count": 0,
                "na_count": 0,
                "fault_hours": 0.0,
            },
        )
        st = str(row["status"]).upper()
        if st == "FAULT":
            rec["fault_count"] += 1
        elif st in {"PASS", "OK"}:
            rec["pass_count"] += 1
        elif st in {"NOT_APPLICABLE_EQUIPMENT_TYPE", "NOT_APPLICABLE"}:
            rec["na_count"] += 1
        else:
            rec["skip_count"] += 1
        try:
            rec["fault_hours"] += float(row["fault_hours"] or 0)
        except (TypeError, ValueError):
            pass
    _write_csv(bundle_dir / "fdd_summary.csv", list(summary_map.values()))
    mark("fdd_summary.csv")

    (bundle_dir / "fault_intervals.json").write_text(
        json.dumps({"intervals": [], "note": "Rust API does not yet emit sparse intervals"}, indent=2),
        encoding="utf-8",
    )
    mark("fault_intervals.json")

    sched = _load(capture_dir / "parity_schedule.json") or {}
    _write_json(bundle_dir / "parity_schedule.json", sched)
    mark("parity_schedule.json")

    sc = _load(capture_dir / "session_config.json") or {}
    _, sc_body = _unwrap(sc) if isinstance(sc, dict) else (None, sc)
    cfg = sc_body.get("config") if isinstance(sc_body, dict) else sc_body
    _write_json(bundle_dir / "session_config.json", cfg if isinstance(cfg, dict) else {})
    mark("session_config.json")

    runtime = _analytics(_unwrap(_load(capture_dir / "runtime.json") or {})[1])
    motor = []
    for eq in runtime.get("equipment") or []:
        if not isinstance(eq, dict):
            continue
        motor.append(
            {
                "equipment_id": eq.get("equipment_id") or "",
                "signal": "runtime",
                "motor_kind": eq.get("plant_group") or "",
                "run_hours": eq.get("run_hours"),
                "on_samples": eq.get("on_samples"),
                "samples": eq.get("samples"),
            }
        )
    _write_csv(bundle_dir / "motor_hours.csv", motor)
    mark("motor_hours.csv")
    weekly = [r for r in (runtime.get("rows") or []) if isinstance(r, dict)]
    _write_csv(bundle_dir / "motor_weekly.csv", weekly)
    mark("motor_weekly.csv")

    sensor = _analytics(_unwrap(_load(capture_dir / "sensor_health.json") or {})[1])
    health_rows = [r for r in (sensor.get("equipment") or sensor.get("rows") or []) if isinstance(r, dict)]
    _write_csv(bundle_dir / "sensor_health_matrix.csv", health_rows)
    mark("sensor_health_matrix.csv")
    _write_csv(bundle_dir / "sensor_fault_summary.csv", health_rows)
    mark("sensor_fault_summary.csv")
    _write_csv(bundle_dir / "sensor_stats_all.csv", health_rows)
    mark("sensor_stats_all.csv")

    schedule = _analytics(_unwrap(_load(capture_dir / "schedule.json") or {})[1])
    sched_rows = [r for r in (schedule.get("rows") or schedule.get("equipment") or []) if isinstance(r, dict)]
    _write_csv(bundle_dir / "schedule_inference_table.csv", sched_rows)
    mark("schedule_inference_table.csv")
    _write_json(bundle_dir / "schedule_inference.json", {"rows": sched_rows, "engine": schedule.get("engine")})
    mark("schedule_inference.json")

    extra = _load(capture_dir / "extra_analytics.json") or {}
    if not isinstance(extra, dict):
        extra = {}
    if "vav_health" not in extra:
        cap_vh = _load(capture_dir / "vav_health.json")
        if cap_vh is not None:
            extra["vav_health"] = cap_vh

    def _extra_rows(name: str) -> list[dict]:
        wrap = extra.get(name) or {}
        st, body = _unwrap(wrap) if isinstance(wrap, dict) else (None, wrap)
        if st not in (None, 200):
            missing_apis.append(name)
            return []
        return [r for r in _rows_of(body) if isinstance(r, dict)]

    mech = _extra_rows("mechanical_cooling")
    _write_csv(bundle_dir / "mech_cooling_oat_bins.csv", mech)
    mark("mech_cooling_oat_bins.csv")
    _write_csv(bundle_dir / "mech_cooling_coverage.csv", mech)
    mark("mech_cooling_coverage.csv")

    econ = _extra_rows("economizer")
    _write_csv(bundle_dir / "economizer_weather.csv", econ)
    mark("economizer_weather.csv")
    _write_csv(bundle_dir / "operating_signatures.csv", econ)
    mark("operating_signatures.csv")

    oat = _extra_rows("bas_vs_web_oat")
    _write_csv(bundle_dir / "weather_observed.csv", oat)
    mark("weather_observed.csv")

    meters = _extra_rows("metering")
    _write_csv(bundle_dir / "meter_monthly_electric.csv", meters)
    mark("meter_monthly_electric.csv")

    rcx_vav = _extra_rows("rcx_vav")
    rcx_preset = _extra_rows("rcx_preset")
    _write_csv(bundle_dir / "rcx_zone_comfort_ranking.csv", rcx_vav)
    mark("rcx_zone_comfort_ranking.csv")
    _write_csv(bundle_dir / "rcx_preset_coverage.csv", rcx_preset)
    mark("rcx_preset_coverage.csv")

    setpoints = _extra_rows("setpoints")
    _write_csv(bundle_dir / "setpoints.csv", setpoints)
    mark("setpoints.csv")
    if not setpoints:
        missing_apis.append("missing_table:setpoints.csv")

    diurnal = _extra_rows("diurnal")
    _write_csv(bundle_dir / "sensor_diurnal_24h.csv", diurnal)
    mark("sensor_diurnal_24h.csv")
    if not diurnal:
        missing_apis.append("missing_table:sensor_diurnal_24h.csv")

    topo_wrap = extra.get("topology") or {}
    _, topo_body = _unwrap(topo_wrap) if isinstance(topo_wrap, dict) else (None, topo_wrap)
    topo_env = _analytics(topo_body) if isinstance(topo_body, dict) else {}
    topo_rows = [r for r in (topo_env.get("rows") or []) if isinstance(r, dict)]
    data_model_rows = [r for r in (topo_env.get("equipment") or []) if isinstance(r, dict)]
    _write_csv(bundle_dir / "topology.csv", topo_rows)
    mark("topology.csv")
    _write_csv(bundle_dir / "data_model.csv", data_model_rows)
    mark("data_model.csv")
    if not topo_rows:
        missing_apis.append("missing_table:topology.csv")

    stats_all = _extra_rows("sensor_stats_all")
    _write_csv(bundle_dir / "sensor_stats_all.csv", stats_all or health_rows)
    mark("sensor_stats_all.csv")

    # Fan-on / fan-off stats: same endpoint, series.fan_state captured separately
    # when capture_extra posts with body variants (see capture_extra).
    stats_on = _extra_rows("sensor_stats_fan_on")
    _write_csv(bundle_dir / "sensor_stats_fan_on.csv", stats_on)
    mark("sensor_stats_fan_on.csv")
    if not stats_on:
        missing_apis.append("missing_table:sensor_stats_fan_on.csv")
    stats_off = _extra_rows("sensor_stats_fan_off")
    _write_csv(bundle_dir / "sensor_stats_fan_off.csv", stats_off)
    mark("sensor_stats_fan_off.csv")
    if not stats_off:
        missing_apis.append("missing_table:sensor_stats_fan_off.csv")

    vh_wrap = extra.get("vav_health") or {}
    _, vh_body = _unwrap(vh_wrap) if isinstance(vh_wrap, dict) else (None, vh_wrap)
    vh_env = _analytics(vh_body) if isinstance(vh_body, dict) else {}
    vh_rows = [r for r in (vh_env.get("rows") or []) if isinstance(r, dict)]
    _write_csv(bundle_dir / "vav_health_matrix.csv", vh_rows)
    mark("vav_health_matrix.csv")
    cov = vh_env.get("coverage") if isinstance(vh_env.get("coverage"), dict) else {}
    _write_json(
        bundle_dir / "vav_health_summary.json",
        {
            "schema_version": vh_env.get("schema_version") or cov.get("schema_version"),
            "groups": cov.get("groups"),
            "row_count": len(vh_rows),
            "engine": vh_env.get("engine"),
            "warnings": vh_env.get("warnings") or [],
        },
    )
    mark("vav_health_summary.json")
    if not vh_rows:
        missing_apis.append("missing_table:vav_health_matrix.csv")

    _write_json(
        bundle_dir / "quality_flags.json",
        {"note": "Rust FDD APIs do not yet return SENTINEL/IMPOSSIBLE_FOR_ROLE flags"},
    )
    mark("quality_flags.json")
    _write_json(bundle_dir / "package_health.json", {"errors": [], "error_count": 0})
    mark("package_health.json")
    _write_json(
        bundle_dir / "effective_catalog.json",
        {"note": "see rust registry; catalog hash compared via inventory"},
    )
    mark("effective_catalog.json")

    manifest = {
        "product": "OpenFDD Engineering Bundle",
        "schema_version": "openfdd_engineering_bundle_v1",
        "legacy_schema_version": "wattlab_dump_v3",
        "engine": "datafusion",
        "rust_engine_version": version,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "files": written,
        "provenance_incomplete": bool(missing_apis),
        "missing_apis": missing_apis,
        "source": "wattlab_parity_ofdd_rust_bundle.py",
    }
    _write_json(bundle_dir / "MANIFEST.json", manifest)
    (bundle_dir / "README.md").write_text(
        "# OpenFDD Engineering Bundle (DataFusion assembler)\n\n"
        "Assembled from Rust JWT APIs — not pandas tools/wattlab_export.\n",
        encoding="utf-8",
    )
    meta = _load(capture_dir / "parity_meta.json") or {}
    if isinstance(meta, dict):
        meta = dict(meta)
        meta["bundle_dir"] = str(bundle_dir)
        meta["missing_apis"] = missing_apis
        _write_json(bundle_dir / "parity_meta.json", meta)
    return manifest


def capture_extra(base: str, token: str | None, building_id: str, capture_dir: Path) -> None:
    extra = {}
    body = {"building_id": building_id}
    for name, path in EXTRA_ANALYTICS:
        st, env = _req("POST", f"{base}{path}", token=token, body=body)
        extra[name] = {"status": st, "body": env}
    for fan_state, key in (("on", "sensor_stats_fan_on"), ("off", "sensor_stats_fan_off")):
        st, env = _req(
            "POST",
            f"{base}/api/analytics/sensor-stats",
            token=token,
            body={"building_id": building_id, "series": {"fan_state": fan_state}},
        )
        extra[key] = {"status": st, "body": env}
    _write_json(capture_dir / "extra_analytics.json", extra)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--building-id", default="BUILDING_100")
    p.add_argument("--schedule", type=Path, default=DEFAULT_SCHED)
    p.add_argument("--capture-out", type=Path, default=DEFAULT_CAPTURE)
    p.add_argument("--out", type=Path, default=DEFAULT_BUNDLE)
    p.add_argument("--session-path", type=Path, default=DEFAULT_SESSION)
    p.add_argument("--admin-password", default=os.environ.get("OPENFDD_ADMIN_PASSWORD", ""))
    p.add_argument("--skip-capture", action="store_true")
    args = p.parse_args()

    if not args.skip_capture:
        sys.argv = [
            "wattlab_parity_ofdd_rust_capture.py",
            "--base",
            args.base,
            "--building-id",
            args.building_id,
            "--schedule",
            str(args.schedule),
            "--out",
            str(args.capture_out),
            "--session-path",
            str(args.session_path),
        ]
        if args.admin_password:
            sys.argv.extend(["--admin-password", args.admin_password])
        rc = capture_main()
        if rc not in (0, 4):
            return rc
        token = login(args.base, args.admin_password) if args.admin_password else None
        capture_extra(args.base, token, args.building_id, args.capture_out)
    else:
        extra_path = args.capture_out / "extra_analytics.json"
        if not extra_path.is_file():
            try:
                token = login(args.base, args.admin_password) if args.admin_password else None
                capture_extra(args.base, token, args.building_id, args.capture_out)
            except Exception as exc:
                print(f"extra analytics skipped (central down): {exc}")
                extra_path.write_text("{}", encoding="utf-8")

    manifest = assemble(args.capture_out, args.out)
    print(f"ofdd rust bundle -> {args.out} files={len(manifest.get('files') or [])}")
    if manifest.get("missing_apis"):
        print(f"missing_apis={manifest['missing_apis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
