"""DEPRECATED — use scripts/gen_openfdd_building_maps.py (BUILDING_100 + BUILDING_50).

One-shot: write openfdd JSON maps into TADCO BUILDING_100 for Cloud zip upload.
"""

from __future__ import annotations

import json
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

SRC = Path(
    r"C:\Users\ben\OneDrive\Desktop\testing\tadco_openfdd_sidecar"
    r"\workspace\imports\hvac_systems_CLEANED"
)
BLDG = SRC / "BUILDING_100"
WX = SRC / "weather"


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
    }.get(et, et or "unknown")


def main() -> None:
    assert BLDG.is_dir(), BLDG
    assert WX.is_dir(), WX

    old_manifest: dict = {}
    mp = BLDG / "manifest.json"
    if mp.is_file():
        old_manifest = json.loads(mp.read_text(encoding="utf-8"))
        bak = BLDG / "manifest.sidecar_backup.json"
        if not bak.is_file():
            bak.write_text(json.dumps(old_manifest, indent=2) + "\n", encoding="utf-8")
            print("backed up manifest ->", bak.name)

    manifest = {
        "schema_version": "openfdd_package_v1",
        "building_id": "BUILDING_100",
        "grid_minutes": int(old_manifest.get("grid_minutes", 5)),
        "timezone": "UTC",
        "notes": (
            "TADCO BUILDING_100 cleaned historian + weather. "
            "Put weather/ inside this folder when zipping. "
            f"site_id={old_manifest.get('site_id', '')}"
        ),
        "site_id": old_manifest.get("site_id", "COMMERCIAL_SITE_A"),
        "weather": "weather/history_wide.csv",
        "weather_location_id": old_manifest.get("weather_location_id", "WX_SITE_01"),
    }
    PackageManifest.model_validate(manifest)
    mp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote", mp)

    equip = discover_equipment(BLDG)
    print(f"equipment discovered: {len(equip)}")
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
        building_id="BUILDING_100",
        site_ref=str(old_manifest.get("site_id") or "COMMERCIAL_SITE_A"),
        generated_by="heuristic_columns_csv",
    )

    written = 0
    empty: list[str] = []
    for eq in equip:
        eq_id = eq["equipment_id"]
        block = (pkg_map.get("equipment") or {}).get(eq_id) or {}
        roles = dict(block.get("column_roles") or {})
        if not roles:
            empty.append(eq_id)
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
            "generated_by": "heuristic_columns_csv",
            "notes": "Auto from columns.csv + header heuristics; refine in UI if needed.",
        }
        out = Path(eq["folder"]) / "column_map.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written += 1
    print(f"wrote {written} column_map.json sidecars; empty_roles={empty}")

    root_cm = BLDG / "column_map.json"
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
    scp = BLDG / "session_config.json"
    scp.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    print("wrote", scp.name, "equip in role_map:", len(role_map))

    readme = BLDG / "_VIBE19_ZIP_README.txt"
    readme.write_text(
        """Vibe19 / openfdd_package_v1 zip instructions
==========================================

Required zip layout (weather MUST live inside BUILDING_100):

  BUILDING_100_openfdd.zip
    BUILDING_100/
      manifest.json
      session_config.json
      column_map.json
      AHU_*/… + column_map.json
      VAV/<box>/… + column_map.json
      weather/history_wide.csv
      weather/columns.csv

PowerShell (from hvac_systems_CLEANED):

  Copy-Item -Recurse -Force .\\weather .\\BUILDING_100\\weather

  $dest = \"$env:USERPROFILE\\Desktop\\BUILDING_100_openfdd.zip\"
  if (Test-Path $dest) { Remove-Item $dest }
  Compress-Archive -Path .\\BUILDING_100 -DestinationPath $dest

Upload that zip to the latest vibe19 build.

Exclude ``quality.json`` / ``fdd_*.csv`` only if you need a smaller zip — the default
entry cap is **2000** (BUILDING_100-style packages with maps are fine).
""",
        encoding="utf-8",
    )
    print("wrote", readme)

    for k in ("AHU_1", "AHU_2", "CHILLER_1", "BOILERS_PUMPS", "VAVFC_100"):
        roles = role_map.get(k, {})
        preview = {
            r: roles.get(r)
            for r in (
                "discharge-air-temp",
                "outside-air-temp",
                "fan-status",
                "mixed-air-temp",
                "return-air-temp",
                "zone-air-temp",
                "chilled-water-supply-temp",
                "hot-water-supply-temp",
                "elec-power",
                "duct-static-pressure",
            )
            if roles.get(r)
        }
        print(k, "->", preview)


if __name__ == "__main__":
    main()
