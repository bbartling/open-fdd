"""Write openfdd JSON maps into TADCO BUILDING_* folders (100 / 50) + weather notes.

Maps 0–100% AOs by role (valve / damper / fan / pump cmd) — not by a point named Loop.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from app.agent_api import make_session_config
from app.column_map_json import (
    COOKBOOK_TO_HAYSTACK_POINT,
    build_column_map_from_equipment_frames,
    column_map_to_role_map,
)
from app.data_loader import discover_equipment
from app.package_io import PackageManifest, SessionConfig
from app.site_model import equipment_type_from_id

DEFAULT_SRC = Path(
    r"C:\Users\ben\OneDrive\Desktop\testing\tadco_openfdd_sidecar"
    r"\workspace\imports\hvac_systems_CLEANED"
)

# Roles we want visible in regen preview (AO + proofs)
_PREVIEW_ROLES = (
    "discharge-air-temp",
    "outside-air-temp",
    "fan-status",
    "fan-cmd",
    "return-fan-cmd",
    "outside-air-damper",
    "cooling-valve",
    "heating-valve",
    "damper",
    "reheat-valve",
    "zone-air-temp",
    "chilled-water-supply-temp",
    "hot-water-supply-temp",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "chw-pump-status",
    "pump-status",
    "duct-static-pressure",
)


def _hs_equip_type(eq_id: str, cookbook_type: str) -> str:
    et = (cookbook_type or "").lower()
    if "CHILLER" in eq_id.upper():
        return "chwPlant"
    if "BOILER" in eq_id.upper():
        return "boiler"
    return {
        "ahu": "ahu",
        "vav": "vav",
        "chiller": "chwPlant",
        "boiler": "boiler",
        "heatpump": "heatPump",
        "pump": "pump",
        "cooling_tower": "coolingTower",
    }.get(et, et or "unknown")


def regen_building(src: Path, building_id: str, *, copy_weather: bool = True) -> None:
    bldg = src / building_id
    wx = src / "weather"
    assert bldg.is_dir(), bldg
    assert wx.is_dir(), wx

    old_manifest: dict = {}
    mp = bldg / "manifest.json"
    if mp.is_file():
        old_manifest = json.loads(mp.read_text(encoding="utf-8"))
        bak = bldg / "manifest.sidecar_backup.json"
        if not bak.is_file():
            bak.write_text(json.dumps(old_manifest, indent=2) + "\n", encoding="utf-8")
            print("backed up manifest ->", bak.name)

    manifest = {
        "schema_version": "openfdd_package_v1",
        "building_id": building_id,
        "grid_minutes": int(old_manifest.get("grid_minutes", 5)),
        "timezone": "UTC",
        "notes": (
            f"TADCO {building_id} cleaned historian + weather. "
            "AO roles = valve/damper/fan/pump cmds (not Loop-named points). "
            f"site_id={old_manifest.get('site_id', '')}"
        ),
        "site_id": old_manifest.get("site_id", "COMMERCIAL_SITE_A"),
        "weather": "weather/history_wide.csv",
        "weather_location_id": old_manifest.get("weather_location_id", "WX_SITE_01"),
    }
    PackageManifest.model_validate(manifest)
    mp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote", mp)

    if copy_weather:
        dest_wx = bldg / "weather"
        dest_wx.mkdir(parents=True, exist_ok=True)
        for name in ("history_wide.csv", "columns.csv"):
            src_f = wx / name
            if src_f.is_file():
                shutil.copy2(src_f, dest_wx / name)
                print("copied", src_f.name, "->", dest_wx / name)

    equip = discover_equipment(bldg)
    print(f"{building_id} equipment discovered: {len(equip)}")
    frames: dict[str, pd.DataFrame] = {}
    for eq in equip:
        hist = Path(eq["history_path"])
        cols_path = eq.get("columns_path")
        header = pd.read_csv(hist, nrows=0)
        df = pd.DataFrame(columns=list(header.columns))
        df.attrs["equipment_id"] = eq["equipment_id"]
        df.attrs["columns_path"] = str(cols_path) if cols_path else None
        df.attrs["equipment_type"] = equipment_type_from_id(eq["equipment_id"])
        frames[eq["equipment_id"]] = df

    pkg_map = build_column_map_from_equipment_frames(
        frames,
        building_id=building_id,
        site_ref=str(old_manifest.get("site_id") or "COMMERCIAL_SITE_A"),
        generated_by="heuristic_ao_roles_v2",
    )

    written = 0
    empty: list[str] = []
    ao_counts = 0
    for eq in equip:
        eq_id = eq["equipment_id"]
        block = (pkg_map.get("equipment") or {}).get(eq_id) or {}
        roles = dict(block.get("column_roles") or {})
        if not roles:
            empty.append(eq_id)
        from app.rules.cookbook_catalog import CONTROL_OUTPUT_ROLES

        if any(r in roles for r in CONTROL_OUTPUT_ROLES):
            ao_counts += 1
        points = {
            COOKBOOK_TO_HAYSTACK_POINT.get(role, role.replace("_", "-")): col
            for role, col in sorted(roles.items())
        }
        cookbook_type = str(block.get("equipment_type") or equipment_type_from_id(eq_id))
        payload = {
            "equipType": _hs_equip_type(eq_id, cookbook_type),
            "device": eq_id,
            "equipment_type": cookbook_type,
            "points": points,
            "column_roles": roles,
            "generated_by": "heuristic_ao_roles_v2",
            "notes": (
                "Auto from columns.csv + header heuristics. "
                "PID-HUNT AOs = valve/damper/fan/pump cmds — not Loop point names."
            ),
        }
        out = Path(eq["folder"]) / "column_map.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written += 1
    print(f"wrote {written} column_map.json sidecars; empty_roles={len(empty)}; with_AO={ao_counts}")

    root_cm = bldg / "column_map.json"
    root_cm.write_text(json.dumps(pkg_map, indent=2) + "\n", encoding="utf-8")
    print("wrote", root_cm.name)

    role_map = column_map_to_role_map(pkg_map)
    session = make_session_config(
        role_map,
        {},
        unit_system="imperial",
        prefer_web_oat=True,
        chw_leave_max_f=48.0,
        include_ahu_chw_valve=False,
    )
    SessionConfig.model_validate(session)
    scp = bldg / "session_config.json"
    scp.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    print("wrote", scp.name, "equip in role_map:", len(role_map))

    for k in ("AHU_1", "AHU_2", "CHILLER_1", "BOILERS_PUMPS", "VAVFC_100", "VAV_1"):
        roles = role_map.get(k, {})
        if not roles:
            # try nested VAV path keys
            hit = next((rk for rk in role_map if rk.endswith(k) or rk == k), None)
            roles = role_map.get(hit or "", {})
            k = hit or k
        preview = {r: roles.get(r) for r in _PREVIEW_ROLES if roles.get(r)}
        if preview:
            print(k, "->", preview)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--src",
        type=Path,
        default=DEFAULT_SRC,
        help="hvac_systems_CLEANED root (BUILDING_* + weather)",
    )
    ap.add_argument(
        "--buildings",
        nargs="+",
        default=["BUILDING_100", "BUILDING_50"],
        help="Building folder names under --src",
    )
    ap.add_argument("--no-copy-weather", action="store_true")
    args = ap.parse_args()
    for bid in args.buildings:
        print("===", bid)
        regen_building(args.src, bid, copy_weather=not args.no_copy_weather)


if __name__ == "__main__":
    main()
