#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected snippet not found in {path}: {old!r}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "services/central/src/analytics/plant_health.rs",
    "use super::historian::{plant_group_for, try_register_history_scoped};",
    "use super::historian::try_register_history_scoped;",
)
replace_once(
    "services/central/src/analytics/plant_health.rs",
    "pub fn matches_family(family: PlantFamily, equipment_id: &str) -> bool {\n",
    "#[cfg(test)]\npub fn matches_family(family: PlantFamily, equipment_id: &str) -> bool {\n",
)
replace_once(
    "services/central/src/analytics/historian.rs",
    "                        plant_signal_label(&cols),\n                        &stamped_types,\n                    )",
    "                        (plant_signal_label(&cols), &stamped_types),\n                    )",
)
replace_once(
    "services/central/src/analytics/historian.rs",
    "    signal_label: &str,\n    stamped_types: &BTreeMap<String, String>,\n) -> Result<Vec<Value>> {\n",
    "    metadata: (&str, &BTreeMap<String, String>),\n) -> Result<Vec<Value>> {\n    let (signal_label, stamped_types) = metadata;\n",
)
