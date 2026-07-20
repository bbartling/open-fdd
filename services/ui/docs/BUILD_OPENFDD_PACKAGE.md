# Build an `openfdd_package_v1` zip for Streamlit / GHCR upload

**Audience:** humans pointing an agent at this file, or agents preparing a building for vibe19.

**Paste this path into the agent chat:**

```text
vibe_code_apps_19/docs/BUILD_OPENFDD_PACKAGE.md
```

Also load [`PACKAGE_SPEC.md`](PACKAGE_SPEC.md) (layout + caps) and [`../AGENTS.md`](../AGENTS.md) (hard rules).

---

## Goal

Turn a cleaned HVAC tree (`BUILDING_*` + sibling `weather/`) into a zip the app accepts on **Zip package** upload:

1. Valid `manifest.json` (`openfdd_package_v1`)
2. **Per-equipment** Haystack map next to every `history_wide.csv` (required)
3. Optional but recommended: `session_config.json` (Units / prefer web OAT / role_map)
4. `weather/` **inside** the building folder (not only a sibling `../weather`)
5. Zip → upload to local Streamlit, GHCR image, or Streamlit Cloud

---

## Required zip layout

```text
BUILDING_100_openfdd.zip
  BUILDING_100/                    # or files at zip root — one folder with manifest.json
    manifest.json                  # REQUIRED — openfdd_package_v1
    session_config.json            # recommended
    column_map.json                # optional root supplement (does NOT replace per-equip maps)
    weather/
      history_wide.csv             # web OAT — map JSON NOT required
      columns.csv                  # optional
    AHU_1/
      history_wide.csv
      columns.csv                  # optional role hints
      column_map.json              # REQUIRED (or history_wide.json / history_wide.column_map.json)
    VAV/
      VAV_1/
        history_wide.csv
        column_map.json
    …
```

**Cloud rejects** the package if any equipment `history_wide.csv` lacks a sibling map.

---

## Agent checklist (do this)

1. **Discover** every `history_wide.csv` under the building folder (skip `weather/`).
2. **Rewrite `manifest.json`** to at least:

```json
{
  "schema_version": "openfdd_package_v1",
  "building_id": "BUILDING_100",
  "grid_minutes": 5,
  "timezone": "UTC",
  "notes": "optional",
  "weather": "weather/history_wide.csv"
}
```

   Backup any sidecar-only manifest first (e.g. `manifest.sidecar_backup.json`).

3. **For each equipment folder**, write `column_map.json` from `columns.csv` + CSV header heuristics (or LLM). Preferred shape:

```json
{
  "equipType": "ahu",
  "device": "AHU_1",
  "points": {
    "discharge-air-temp": "discharge_air_temp_f",
    "outside-air-temp": "outside_air_temp_f",
    "fan-status": "supply_fan_status"
  }
}
```

   Stamp real `equipType` / `equipment_type` (`ahu`, `vav`, `chwPlant`, `boiler`, …). See [`HAYSTACK_LIKE_MAPPING_GUIDE.md`](HAYSTACK_LIKE_MAPPING_GUIDE.md) and [`COLUMN_MAP_JSON.md`](COLUMN_MAP_JSON.md).

4. **Write `session_config.json`** (`openfdd_session_v1`) with `unit_system`, `prefer_web_oat: true`, and a `role_map` derived from those maps (`app.agent_api.make_session_config` / `column_map_to_role_map`).

5. **Copy** sibling `weather/` → `BUILDING_*/weather/` (app loads `building_root/weather/history_wide.csv` only).

6. **Validate** before handing the zip to a human:

```powershell
cd vibe_code_apps_19
python -c "from pathlib import Path; from app.package_io import load_package_from_dir; r=load_package_from_dir(Path(r'PATH\TO\BUILDING_100')); print(len(r.frames), r.weather is not None, r.session_config is not None)"
```

7. **Zip** the building folder (keep under **500 MB** for browser upload; **≤2000 zip entries** default). Larger jobs: split parts per [`../vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md`](../vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md).

**Do not use PowerShell `Compress-Archive` for Streamlit/Docker/Linux uploads.** It writes backslash paths; on Linux, Python treats `BUILDING_100\VAV\` as a *file* named `VAV`, then nested `VAV/VAVFC_100/...` fails with `[Errno 20] Not a directory`. Use Python `zipfile` with `.as_posix()` arcnames (forward slashes only):

```powershell
# From tadco sidecar (preferred)
python workspace/zip_openfdd_buildings.py

# Or inline
python -c "import zipfile; from pathlib import Path; b=Path(r'.\BUILDING_100'); z=Path(r'$env:USERPROFILE\OneDrive\Desktop\BUILDING_100_openfdd.zip');
zf=zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED);
[zf.write(p, f'{b.name}/{p.relative_to(b).as_posix()}') for p in b.rglob('*') if p.is_file()]; zf.close(); print(z)"
```

Avoid:

```powershell
# BAD for Linux/Streamlit Cloud / GHCR
Compress-Archive -Path .\BUILDING_100 -DestinationPath "...\BUILDING_100_openfdd.zip"
```

> The app now **normalizes backslash zips automatically** (`_is_zip_dir` in
> `app/package_io.py` treats `folder\` markers as directories), so an existing
> `Compress-Archive` zip will load. Forward-slash arcnames remain the spec —
> other tools reading the package may still choke on backslashes.

8. Human uploads the zip in the Streamlit sidebar (**Data source → Zip package**).

---

## Helper in this repo

Heuristic generator used for TADCO-style trees (both buildings + weather nest + TADCO Haystack overrides):

```powershell
cd vibe_code_apps_19
python scripts/gen_openfdd_building_maps.py
# optional: python scripts/gen_openfdd_building_maps.py --buildings BUILDING_100
```

Prefer reusing `app.column_map_json.build_column_map_from_equipment_frames` over inventing a new mapper. The TADCO script applies post-heuristic overrides (no exhaust-as-OA-damper, no AHU zone SpaceTemp, no chiller enable-SP as OAT).

---

## Related docs

| Doc | Use |
| --- | --- |
| [`PACKAGE_SPEC.md`](PACKAGE_SPEC.md) | Canonical zip contract + size caps |
| [`COLUMN_MAP_JSON.md`](COLUMN_MAP_JSON.md) | Map schema + LLM prompt hooks |
| [`HAYSTACK_LIKE_MAPPING_GUIDE.md`](HAYSTACK_LIKE_MAPPING_GUIDE.md) | Point name table |
| [`STREAMLIT_CLOUD.md`](STREAMLIT_CLOUD.md) | Upload + session restore |
| [`../vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md`](../vibe19_agent_spec/docs/AGENT_CSV_PREPROCESS.md) | Multi-part zips when >500 MB |
| [`../AGENTS.md`](../AGENTS.md) | Session brief / hard rules |
