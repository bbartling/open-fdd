#!/usr/bin/env python3
"""Stage + lightly enhance the OpenFDD synthetic 59-rule golden fixture.

Source handoff ZIP → reports/wattlab-parity/fixtures/synthetic_59/
Enhancements (do not rewrite expected_faults.csv goldens):
  - copy default_confirmation_expectations.csv to outer root
  - add AHU_CASE_SCHED_1_STRING companion + expected_faults_extra.csv
  - emit test_contract/role_map_normalized.json (kebab→snake)
  - re-zip package; refresh checksums.csv / validation_report.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path.home() / "OPENFDD_SYNTHETIC_59_RULE_HANDOFF_V1_20260812_085050.zip"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/fixtures/synthetic_59"

# Mirrors edge/src/csv_ingest/package.rs haystack_point_to_role (explicit arms).
HAYSTACK_TO_SNAKE: dict[str, str] = {
    "discharge-air-temp": "sat",
    "discharge-air-temp-sp": "sat_sp",
    "mixed-air-temp": "mat",
    "return-air-temp": "rat",
    "outside-air-temp": "oa_t",
    "bas-outside-air-temp": "oa_t",
    "outside-air-humidity": "oa_h",
    "outside-air-damper": "oa_damper_pct",
    "cooling-valve": "clg_valve_pct",
    "heating-valve": "htg_valve_pct",
    "fan-cmd": "fan_cmd",
    "return-fan-cmd": "return_fan",
    "fan-status": "fan_status",
    "duct-static-pressure": "duct_static",
    "duct-static-pressure-sp": "duct_static_sp",
    "vav-pressure-request-sum": "static_reset_request",
    "static-reset-request": "static_reset_request",
    "cooling-coil-entering-temp": "cooling_coil_entering_temp",
    "cooling-coil-leaving-temp": "cooling_coil_leaving_temp",
    "heating-coil-entering-temp": "heating_coil_entering_temp",
    "heating-coil-leaving-temp": "heating_coil_leaving_temp",
    "chiller-status": "chiller_status",
    "loop-enabled": "loop_enabled",
    "zone-air-temp": "zone_t",
    "zone-airflow": "zone_flow",
    "min-flow-sp": "min_flow_sp",
    "damper": "damper_pct",
    "reheat-valve": "reheat_valve_pct",
    "vav-discharge-air-temp": "vav_discharge_t",
    "vav-inlet-air-temp": "vav_inlet_t",
    "ahu-discharge-air-temp": "ahu_sat",
    "chilled-water-supply-temp": "chw_supply_t",
    "chilled-water-return-temp": "chw_return_t",
    "chilled-water-supply-temp-sp": "chw_supply_sp",
    "hot-water-supply-temp": "hw_supply_t",
    "hot-water-return-temp": "hw_return_t",
    "occupied": "occ_mode",
    "chw-diff-pressure": "chw_dp",
    "chw-diff-pressure-sp": "chw_dp_sp",
    "chw-flow": "chw_flow",
    "chw-pump-cmd": "chw_pump_cmd",
    "cw-pump-cmd": "cw_pump_cmd",
    "tower-fan-cmd": "tower_fan_cmd",
    "cw-fan-cmd": "tower_fan_cmd",
    "condenser-water-supply-temp": "cw_supply_t",
    "condenser-water-return-temp": "cw_return_t",
    "preheat-leaving-temp": "preheat_leave_t",
    "web-outside-air-temp": "web_oa_t",
    "web-outside-air-dewpoint": "web_oa_dp",
    "web-outside-air-wetbulb": "web_wb_t",
    "web-outside-air-humidity": "web_oa_h",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def haystack_point_to_role(point: str) -> str:
    slug = point.strip().lower().replace(" ", "-").replace("_", "-")
    if slug in HAYSTACK_TO_SNAKE:
        return HAYSTACK_TO_SNAKE[slug]
    return slug.replace("-", "_")


def unzip_handoff(src: Path, dest: Path) -> Path:
    """Extract handoff ZIP, rewriting Windows backslash entry names into dirs."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # ZIP from Windows may use literal backslashes in the entry name.
            rel = info.filename.replace("\\", "/")
            if rel.endswith("/"):
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src_f, out.open("wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
    nested = dest / "openfdd_synthetic_59_rule_fixture_v1"
    if nested.is_dir() and (nested / "expected_faults.csv").is_file():
        return nested
    kids = [p for p in dest.iterdir() if p.is_dir()]
    if len(kids) == 1 and (kids[0] / "expected_faults.csv").is_file():
        return kids[0]
    for p in dest.rglob("expected_faults.csv"):
        return p.parent
    raise SystemExit(f"could not find fixture root under {dest}")


def unpack_package(fixture_root: Path) -> Path:
    pkg_zip = fixture_root / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip"
    pkg_dir = fixture_root / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1"
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    with zipfile.ZipFile(pkg_zip) as zf:
        zf.extractall(fixture_root)
    if not pkg_dir.is_dir():
        raise SystemExit(f"package dir missing after unzip: {pkg_dir}")
    return pkg_dir


def copy_confirmation_csv(pkg_dir: Path, fixture_root: Path) -> Path:
    src = pkg_dir / "test_contract" / "default_confirmation_expectations.csv"
    if not src.is_file():
        raise SystemExit(f"missing {src}")
    dst = fixture_root / "default_confirmation_expectations.csv"
    shutil.copy2(src, dst)
    # keep test_contract copy in sync
    return dst


def build_role_map_normalized(pkg_dir: Path) -> Path:
    roles: dict[str, str] = {}
    for cm in pkg_dir.rglob("column_map.json"):
        if "test_contract" in cm.parts:
            continue
        data = json.loads(cm.read_text())
        col_roles = data.get("column_roles") or data.get("points") or {}
        for raw in col_roles.values():
            if not isinstance(raw, str):
                continue
            roles[raw] = haystack_point_to_role(raw)
        for raw in col_roles.keys():
            if isinstance(raw, str) and "-" in raw:
                roles.setdefault(raw, haystack_point_to_role(raw))
    out = {
        "schema": "openfdd_synthetic_role_map_normalized_v1",
        "source": "haystack_point_to_role (package.rs mirror)",
        "mapping": dict(sorted(roles.items())),
        "count": len(roles),
    }
    dest = pkg_dir / "test_contract" / "role_map_normalized.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    # also outer copy for handoff consumers
    (pkg_dir.parent / "role_map_normalized.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    return dest


def add_sched1_string_companion(pkg_dir: Path, fixture_root: Path) -> None:
    src_eq = pkg_dir / "AHU_CASE_SCHED_1"
    dst_eq = pkg_dir / "AHU_CASE_SCHED_1_STRING"
    if not src_eq.is_dir():
        raise SystemExit(f"missing {src_eq}")
    if dst_eq.exists():
        shutil.rmtree(dst_eq)
    shutil.copytree(src_eq, dst_eq)

    # Rewrite history: map occupied 1→occupied, 0→unoccupied
    hist = dst_eq / "history_wide.csv"
    rows = list(csv.DictReader(hist.open()))
    if not rows or "occupied" not in rows[0]:
        raise SystemExit("SCHED-1 history missing occupied column")
    fieldnames = list(rows[0].keys())
    for r in rows:
        v = str(r["occupied"]).strip()
        if v in ("1", "1.0", "true", "True"):
            r["occupied"] = "occupied"
        elif v in ("0", "0.0", "false", "False"):
            r["occupied"] = "unoccupied"
    with hist.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # column_map / columns equipment id
    cm_path = dst_eq / "column_map.json"
    cm = json.loads(cm_path.read_text())
    cm["device"] = "AHU_CASE_SCHED_1_STRING"
    cm["test_target_rule_id"] = "SCHED-1"
    cm["notes"] = (
        "Companion to AHU_CASE_SCHED_1: literal occupied/unoccupied strings "
        "for the same Wed 11:00-12:00 UTC window. Additive probe — does not "
        "replace the numeric 0/1 golden in expected_faults.csv."
    )
    cm_path.write_text(json.dumps(cm, indent=2) + "\n")

    cols_path = dst_eq / "columns.csv"
    col_rows = list(csv.DictReader(cols_path.open()))
    if col_rows:
        fn = list(col_rows[0].keys())
        for r in col_rows:
            if "equipment_id" in r:
                r["equipment_id"] = "AHU_CASE_SCHED_1_STRING"
        with cols_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            w.writerows(col_rows)

    # expected_faults_extra.csv (outer + test_contract)
    primary = list(csv.DictReader((fixture_root / "expected_faults.csv").open()))
    sched = next(r for r in primary if r["rule_id"] == "SCHED-1")
    extra = dict(sched)
    extra["ordinal"] = "59b"
    extra["equipment_id"] = "AHU_CASE_SCHED_1_STRING"
    extra["injection_note"] = (
        (extra.get("injection_note") or "")
        + " | STRING occupancy companion (occupied/unoccupied literals)"
    ).strip(" |")
    extra_path = fixture_root / "expected_faults_extra.csv"
    with extra_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(extra.keys()))
        w.writeheader()
        w.writerow(extra)
    shutil.copy2(extra_path, pkg_dir / "test_contract" / "expected_faults_extra.csv")


def rezip_package(pkg_dir: Path, fixture_root: Path) -> Path:
    out_zip = fixture_root / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip"
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pkg_dir.rglob("*")):
            if path.is_file():
                arc = path.relative_to(fixture_root).as_posix()
                zf.write(path, arcname=arc)
    return out_zip


def refresh_checksums(fixture_root: Path) -> None:
    # Track key handoff files (existing + new)
    names = [
        "CURSOR_AGENT_PROMPT.md",
        "README.md",
        "checksums.csv",
        "default_confirmation_expectations.csv",
        "equation_review.csv",
        "equipment_legend.csv",
        "expected_faults.csv",
        "expected_faults_extra.csv",
        "OpenFDD_Synthetic_59_Rule_Legend.xlsx",
        "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip",
        "point_legend.csv",
        "role_map_normalized.json",
        "rule_catalog.csv",
        "runtime_legend.csv",
        "validation_report.json",
        "verification_observed.csv",
        "verification_summary.json",
        "vibe19_integration_observed.csv",
        "vibe19_integration_summary.json",
    ]
    rows = []
    for name in names:
        p = fixture_root / name
        if not p.is_file():
            continue
        rows.append(
            {
                "file": name,
                "sha256": sha256_file(p),
                "bytes": str(p.stat().st_size),
            }
        )
    # write checksums without hashing itself first — then rewrite with self hash omitted
    ck = fixture_root / "checksums.csv"
    with ck.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "sha256", "bytes"])
        w.writeheader()
        w.writerows([r for r in rows if r["file"] != "checksums.csv"])
    # include checksums.csv entry with hash of content without self — skip self
    # (common pattern: list peers only)


def refresh_validation_report(fixture_root: Path, pkg_zip: Path) -> None:
    path = fixture_root / "validation_report.json"
    prev = {}
    if path.is_file():
        prev = json.loads(path.read_text())
    assertions = dict(prev.get("assertions") or {})
    assertions["outer_has_default_confirmation"] = (
        fixture_root / "default_confirmation_expectations.csv"
    ).is_file()
    assertions["has_sched1_string_companion"] = (
        fixture_root / "OPENFDD_SYNTHETIC_59_RULE_WEEK_V1" / "AHU_CASE_SCHED_1_STRING"
    ).is_dir()
    assertions["has_role_map_normalized"] = (
        fixture_root / "role_map_normalized.json"
    ).is_file()
    assertions["has_expected_faults_extra"] = (
        fixture_root / "expected_faults_extra.csv"
    ).is_file()
    report = {
        "status": prev.get("status", "PASS"),
        "fixture_note": (
            "Staged + enhanced for OpenFDD/Vibe19 target-pair soak. "
            "Primary goldens unchanged (58/59; SCHED-1 numeric occupancy defect). "
            "AHU_CASE_SCHED_1_STRING is additive (expected_faults_extra.csv)."
        ),
        "staged_at_utc": datetime.now(timezone.utc).isoformat(),
        "zip_bytes": pkg_zip.stat().st_size,
        "zip_sha256": sha256_file(pkg_zip),
        "assertions": assertions,
        "failures": prev.get("failures") or [],
    }
    path.write_text(json.dumps(report, indent=2) + "\n")


def write_stage_readme(fixture_root: Path) -> None:
    text = """# Synthetic 59 fixture (staged)

Canonical equation-isolation golden for Vibe19 + OpenFDD SQL target-pair soaks.

- Package: `OPENFDD_SYNTHETIC_59_RULE_WEEK_V1.zip` (also unpacked beside it)
- Primary goldens: `expected_faults.csv` (do not rewrite to match bugs)
- Additive string occupancy probe: `expected_faults_extra.csv` + `AHU_CASE_SCHED_1_STRING`
- Confirmation defaults: `default_confirmation_expectations.csv`
- Role map smoke: `role_map_normalized.json` (kebab→snake, mirrors central ingest)

See `CURSOR_AGENT_PROMPT.md` and repo script `scripts/synthetic_59_target_pair_soak.py`.
"""
    (fixture_root / "STAGED.md").write_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    if not args.src.is_file():
        raise SystemExit(f"handoff zip not found: {args.src}")

    fixture_root = unzip_handoff(args.src, args.out)
    print(f"fixture_root={fixture_root}")
    pkg_dir = unpack_package(fixture_root)
    print(f"package_dir={pkg_dir}")

    conf = copy_confirmation_csv(pkg_dir, fixture_root)
    print(f"copied {conf.name}")
    rm = build_role_map_normalized(pkg_dir)
    print(f"role_map {rm} mappings={json.loads(rm.read_text())['count']}")
    add_sched1_string_companion(pkg_dir, fixture_root)
    print("added AHU_CASE_SCHED_1_STRING + expected_faults_extra.csv")

    pkg_zip = rezip_package(pkg_dir, fixture_root)
    print(f"rezipped {pkg_zip} ({pkg_zip.stat().st_size} bytes)")
    refresh_validation_report(fixture_root, pkg_zip)
    refresh_checksums(fixture_root)
    write_stage_readme(fixture_root)
    print("OK stage complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
