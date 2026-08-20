#!/usr/bin/env python3
from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text()


def write(path: str, text: str) -> None:
    Path(path).write_text(text)


def sub(path: str, pattern: str, repl: str, count: int = 1, flags: int = 0) -> None:
    text = read(path)
    text2, n = re.subn(pattern, repl, text, count=count, flags=flags)
    if n != count:
        raise SystemExit(f"{path}: expected {count} replacement(s), got {n}: {pattern[:120]!r}")
    write(path, text2)


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    if text.count(old) < count:
        raise SystemExit(f"{path}: expected snippet not found: {old[:120]!r}")
    write(path, text.replace(old, new, count))


# 1) Export the generic type registry module.
replace("edge/src/lib.rs", "pub mod csv_ingest;\n", "pub mod csv_ingest;\npub mod equipment_types;\n")

# 2) Package ingest: preserve stamp from sibling/root maps and persist it.
p = "edge/src/csv_ingest/package.rs"
sub(p, r"(struct EquipmentPlan \{.*?\n\s*map_source: String,)(\n\})", r"\1\n    equipment_type: Option<String>,\2", flags=re.S)
replace(p, "        let mut points: Option<BTreeMap<String, String>> = None;\n", "        let mut points: Option<BTreeMap<String, String>> = None;\n        let mut equipment_type: Option<String> = None;\n")
sub(
    p,
    r"(Ok\(v\) => \{\n)(\s*)(points = points_from_map_json\(&v, &equip_id\);)",
    r"\1\2if equipment_type.is_none() {\n\2    equipment_type = crate::equipment_types::stamped_type_from_map_json(&v, &equip_id);\n\2}\n\2\3",
)
replace(
    p,
    "        if points.is_none() {\n            if let Some(root) = &root_map {\n",
    "        if equipment_type.is_none() {\n            if let Some(root) = &root_map {\n                equipment_type = crate::equipment_types::stamped_type_from_map_json(root, &equip_id);\n            }\n        }\n        if points.is_none() {\n            if let Some(root) = &root_map {\n",
)
sub(p, r"(plans\.push\(EquipmentPlan \{.*?\n\s*map_source,)(\n\s*\}\);)", r"\1\n            equipment_type,\2", flags=re.S)

# helper to re-sync cached registry after any re-ingest
anchor = "fn parquet_out_dir() -> PathBuf {"
idx = read(p).index(anchor)
# add helper after parquet_out_dir function by locating next import doc comment
text = read(p)
marker = "\n/// Load `openfdd_package_v1` zip bytes: validate, materialize under\n"
if "fn sync_equipment_types_cache(" not in text:
    helper = '''\nfn sync_equipment_types_cache(\n    building_root: &Path,\n    out_dir: &Path,\n    building_id: &str,\n) -> Result<(), String> {\n    let path = building_root.join(crate::equipment_types::EQUIPMENT_TYPES_FILE);\n    let Ok(body) = std::fs::read_to_string(path) else {\n        return Ok(());\n    };\n    let types: BTreeMap<String, String> = serde_json::from_str(&body)\n        .map_err(|e| format!("equipment type registry parse: {e}"))?;\n    crate::equipment_types::write_type_map(out_dir, building_id, &types)\n}\n'''
    replace(p, marker, helper + marker)

insert = '''    let stamped_types: BTreeMap<String, String> = plans\n        .iter()\n        .filter_map(|plan| {\n            plan.equipment_type\n                .as_ref()\n                .map(|t| (plan.equipment_id.clone(), t.clone()))\n        })\n        .collect();\n    if !stamped_types.is_empty() {\n        match serde_json::to_string_pretty(&stamped_types) {\n            Ok(body) => {\n                if let Err(e) = std::fs::write(\n                    building_root.join(crate::equipment_types::EQUIPMENT_TYPES_FILE),\n                    body,\n                ) {\n                    warnings.push(format!("equipment type registry not materialized: {e}"));\n                }\n            }\n            Err(e) => warnings.push(format!("equipment type registry serialize: {e}")),\n        }\n    }\n\n'''
replace(p, "    let mut equipment_report = Vec::new();\n", insert + "    let mut equipment_report = Vec::new();\n")
replace(
    p,
    "        let unmapped: Vec<&String> = plan\n",
    '''        if let Some(raw_type) = plan.equipment_type.as_deref() {\n            let meta = json!({\n                "equipment_id": plan.equipment_id,\n                "equipType": raw_type,\n                "canonical_kind": crate::equipment_types::canonical_kind(raw_type),\n            });\n            let _ = std::fs::write(\n                eq_dir.join("equipment.json"),\n                serde_json::to_string_pretty(&meta).unwrap_or_default(),\n            );\n        }\n        let unmapped: Vec<&String> = plan\n''',
)
replace(p, '            "map_source": plan.map_source,\n', '            "map_source": plan.map_source,\n            "equipment_type": plan.equipment_type,\n')
replace(
    p,
    "        Ok(report) => {\n            warnings.extend(feather_warnings);\n",
    "        Ok(report) => {\n            warnings.extend(feather_warnings);\n            if let Err(e) = sync_equipment_types_cache(&building_root, &out_dir, &building_id) {\n                warnings.push(e);\n            }\n",
)

# append_package_json success: turn expression arm into block and sync registry
sub(
    p,
    r"(fn append_package_json\(body: &Value\) -> Value \{.*?match fdd_store::ingest_building\(&data_root, &building_id, &out_dir\) \{\n\s*)Ok\(report\) => json!\(\{(.*?)\n\s*\}\),",
    r"\1Ok(report) => {\n            let _ = sync_equipment_types_cache(&building_root, &out_dir, &building_id);\n            json!({\2\n            })\n        },",
    flags=re.S,
)

# update_package_roles_handler success arm
sub(
    p,
    r"(fn update_package_roles_handler\(body: &Value\) -> Value \{.*?\n\s*)Ok\(report\) => json!\(\{(.*?)\n\s*\}\),\n\s*Err\(e\) => json!\(\{\"ok\": false, \"error\": format!\(\"re-ingest failed: \{e:#\}\"\)\}\),",
    r"\1Ok(report) => {\n            let _ = sync_equipment_types_cache(&building_root, &out_dir, &building_id);\n            json!({\2\n            })\n        },\n        Err(e) => json!({\"ok\": false, \"error\": format!(\"re-ingest failed: {e:#}\")}),",
    flags=re.S,
)

# 3) FDD inventory/results prefer persisted stamps.
p = "edge/src/fdd/registry_api.rs"
replace(
    p,
    "    ids.sort();\n    ids.dedup();\n    let equipment: Vec<Value> = ids\n",
    "    ids.sort();\n    ids.dedup();\n    let stamped_types = crate::equipment_types::load_type_map(&parquet_root(), building_id);\n    let equipment: Vec<Value> = ids\n",
)
sub(
    p,
    r"\.map\(\|id\| \{\n\s*json!\(\{\n\s*\"equipment_id\": id,\n\s*\"equipment_type\": infer_equipment_type\(id\),\n\s*\}\)\n\s*\}\)",
    ".map(|id| {\n            let stamped = stamped_types.get(id).map(String::as_str);\n            crate::equipment_types::type_report(id, stamped)\n        })",
)
replace(
    p,
    "pub fn results_response(building_id: Option<&str>) -> Value {\n    let dir = results_dir(building_id);\n",
    "pub fn results_response(building_id: Option<&str>) -> Value {\n    let dir = results_dir(building_id);\n    let stamped_types = crate::equipment_types::load_type_map(&parquet_root(), building_id);\n",
)
replace(
    p,
    "                let kind = infer_equipment_kind(equipment_id);\n",
    "                let stamped = stamped_types.get(equipment_id).map(String::as_str);\n                let kind = crate::equipment_types::kind_for(equipment_id, stamped);\n",
)
replace(
    p,
    '                    "equipment_type": infer_equipment_type(equipment_id),\n',
    '                    "equipment_type": crate::equipment_types::api_equipment_type_for(equipment_id, stamped),\n                    "equipment_type_raw": stamped,\n                    "equipment_type_source": if stamped.and_then(crate::equipment_types::canonical_kind).is_some() { "package" } else { "id" },\n',
)

# 4) Historian plant grouping: stamp first, existing heuristics second.
p = "services/central/src/analytics/historian.rs"
needle = "pub fn plant_group_for(equipment_id: &str) -> Option<&'static str> {\n"
if "pub fn plant_group_for_typed(" not in read(p):
    typed = '''pub fn plant_group_for_typed(\n    equipment_id: &str,\n    stamped_type: Option<&str>,\n) -> Option<&'static str> {\n    if let Some(kind) = stamped_type.and_then(open_fdd_edge_prototype::equipment_types::canonical_kind) {\n        return match kind {\n            "ahu" => Some("air"),\n            "chiller" | "cooling_tower" | "heatpump" => Some("chiller"),\n            "boiler" => Some("boiler"),\n            "vav" | "weather" => None,\n            _ => None,\n        };\n    }\n    plant_group_for(equipment_id)\n}\n\n'''
    replace(p, needle, typed + needle)
replace(
    p,
    "    let max_gap = max_gap_seconds.max(0.0);\n    let eq_filter = equipment_filter_sql(equipment_filter);\n\n    if cols.contains(\"equipment_id\") {\n",
    "    let max_gap = max_gap_seconds.max(0.0);\n    let eq_filter = equipment_filter_sql(equipment_filter);\n    let stamped_types = open_fdd_edge_prototype::equipment_types::load_type_map(&parquet_root(), building_id);\n\n    if cols.contains(\"equipment_id\") {\n",
)
sub(
    p,
    r'"plant_group": plant_group_for\(\n\s*row\.get\("equipment_id"\)\.and_then\(\|v\| v\.as_str\(\)\)\.unwrap_or\(""\)\n\s*\),',
    '"plant_group": plant_group_for_typed(\n                                &eq,\n                                stamped_types.get(&eq).map(String::as_str),\n                            ),',
)
replace(
    p,
    "                    plant_signal_label(&cols),\n                )\n",
    "                    plant_signal_label(&cols),\n                    &stamped_types,\n                )\n",
)
replace(
    p,
    "    signal_label: &str,\n) -> Result<Vec<Value>> {\n",
    "    signal_label: &str,\n    stamped_types: &BTreeMap<String, String>,\n) -> Result<Vec<Value>> {\n",
)
replace(
    p,
    "        let Some(plant) = plant_group_for(eq) else {\n            continue;\n        };\n",
    "        let Some(plant) = plant_group_for_typed(eq, stamped_types.get(eq).map(String::as_str)) else {\n            continue;\n        };\n",
)

# 5) Plant health family matching uses same precedence.
p = "services/central/src/analytics/plant_health.rs"
sub(
    p,
    r"pub fn matches_family\(family: PlantFamily, equipment_id: &str\) -> bool \{.*?\n\}\n",
    '''pub fn matches_family_typed(\n    family: PlantFamily,\n    equipment_id: &str,\n    stamped_type: Option<&str>,\n) -> bool {\n    let stamped_kind = stamped_type.and_then(open_fdd_edge_prototype::equipment_types::canonical_kind);\n    match family {\n        PlantFamily::Ahu => super::historian::plant_group_for_typed(equipment_id, stamped_type) == Some("air"),\n        PlantFamily::Chiller => {\n            super::historian::plant_group_for_typed(equipment_id, stamped_type) == Some("chiller")\n                && stamped_kind != Some("heatpump")\n                && !is_heat_pump_id(equipment_id)\n        }\n        PlantFamily::Boiler => super::historian::plant_group_for_typed(equipment_id, stamped_type) == Some("boiler"),\n        PlantFamily::HeatPump => stamped_kind == Some("heatpump") || is_heat_pump_id(equipment_id),\n    }\n}\n\npub fn matches_family(family: PlantFamily, equipment_id: &str) -> bool {\n    matches_family_typed(family, equipment_id, None)\n}\n''',
    flags=re.S,
)
replace(
    p,
    "    let (has_fdd, index) = fdd_index(bid);\n    let mut seen = 0u32;\n",
    "    let (has_fdd, index) = fdd_index(bid);\n    let stamped_types = open_fdd_edge_prototype::equipment_types::load_type_map(\n        &super::historian::parquet_root(),\n        Some(bid),\n    );\n    let mut seen = 0u32;\n",
)
replace(
    p,
    "        if eq.is_empty() || !matches_family(spec.family, eq) {\n            continue;\n        }\n",
    "        let stamped_type = stamped_types.get(eq).map(String::as_str);\n        if eq.is_empty() || !matches_family_typed(spec.family, eq, stamped_type) {\n            continue;\n        }\n",
)
sub(
    p,
    r"\s*let eq_type = match spec\.family \{.*?\n\s*\};\n",
    "        let eq_type = open_fdd_edge_prototype::equipment_types::api_equipment_type_for(eq, stamped_type);\n",
    flags=re.S,
)
replace(
    p,
    '        assert!(matches_family(PlantFamily::Ahu, "RTU_2"));\n',
    '        assert!(matches_family(PlantFamily::Ahu, "RTU_2"));\n        assert!(matches_family_typed(PlantFamily::Ahu, "AC_1", Some("ahu")));\n        assert!(!matches_family_typed(PlantFamily::Ahu, "AC_1", Some("vav")));\n',
)

# 6) Docs: durable, vendor-neutral contract across authoring/MCP/agent surfaces.
docs = {
    "docs/agent/PACKAGE_AUTHORING.md": """\n\n## Equipment type precedence\n\nStamp each equipment block with `equipType` (preferred) or `equipment_type`. Open-FDD persists that stamp during package ingest and uses it before generic folder/id heuristics for inventory and analytics. Example: a folder named `AC_1` with `equipType: ahu` is treated as an AHU. If the stamp is absent or unrecognized, vendor-neutral id heuristics remain the fallback. Vendor/site-specific aliases belong in the preprocess package generator, never in product Rust.\n""",
    "openfdd_agent_spec/DATA_CONTRACT.md": """\n\n## Equipment type precedence\n\n`equipType` / `equipment_type` is durable package metadata. When present and recognized, it is authoritative for Open-FDD equipment classification; generic equipment-id heuristics are fallback only. `AC_1 + equipType: ahu` must classify as AHU. Keep vendor/campus naming remaps in preprocessors rather than product code.\n""",
    "openfdd_agent_spec/skills/openfdd-package-mapping/SKILL.md": """\n\n## Stamped equipment types\n\nPrefer stamping `equipType` (or `equipment_type`) in each equipment map. Open-FDD persists and prefers the stamp over folder-id inference. If an Overview family is empty for an opaque id such as `AC_1`, stamp the correct generic type instead of adding a vendor/site heuristic to Rust.\n""",
    "openfdd_agent_spec/AGENTS.md": """\n\n### Equipment typing contract\n\nPackage `equipType` / `equipment_type` stamps are persisted and preferred over id heuristics. Opaque ids are valid (`AC_1` + `equipType: ahu`). Never solve a site-specific naming problem by hard-coding a vendor, campus, or building into product code.\n""",
    "mcp/INSTRUCTIONS.md": """\n\n## Equipment typing\n\nDuring package cleaning/modeling, stamp generic `equipType` / `equipment_type` metadata. The product persists and prefers that stamp; folder/id inference is fallback. Empty Overview families on opaque ids are a package-modeling signal, not a reason to add site-specific Rust heuristics.\n""",
    "mcp/README.md": """\n\n### Package equipment types\n\nFor portable package mapping, stamp `equipType` (or `equipment_type`) on equipment blocks. Open-FDD persists the stamp and uses it before generic id heuristics, so opaque BAS ids such as `AC_1` can still classify correctly as `ahu`.\n""",
    "docs/mcp-agents/roles/package-mapping.md": """\n\n## Equipment type hygiene\n\nStamp a generic `equipType` / `equipment_type` whenever the source folder id is opaque. The stamp is persisted by package ingest and wins over id heuristics (`AC_1` + `equipType: ahu` → AHU). Keep vendor/campus remaps in the preprocess repository.\n""",
    "AGENTS.md": """\n\n### Stamped equipment type precedence\n\nPackage ingest persists `equipType` / `equipment_type`; recognized stamps win over folder/id heuristics in inventory and plant-health grouping. Opaque BAS ids are supported (`AC_1` + `equipType: ahu` → AHU). Vendor/campus aliases remain preprocess concerns and must not be hard-coded into product Rust.\n""",
}
for path, addition in docs.items():
    text = read(path)
    heading = addition.strip().splitlines()[0]
    if heading not in text:
        write(path, text.rstrip() + addition + "\n")
