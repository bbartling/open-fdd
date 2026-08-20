#!/usr/bin/env python3
from pathlib import Path

p = Path("scripts/pr2_equipment_type_patch.py")
text = p.read_text()
old = r'''    r"\1Ok(report) => {\n            let _ = sync_equipment_types_cache(&building_root, &out_dir, &building_id);\n            json!({\2\n            })\n        },\n        Err(e) => json!({\"ok\": false, \"error\": format!(\"re-ingest failed: {e:#}\")}),",
'''
new = r'''    r'\1Ok(report) => {\n            let _ = sync_equipment_types_cache(&building_root, &out_dir, &building_id);\n            json!({\2\n            })\n        },\n        Err(e) => json!({"ok": false, "error": format!("re-ingest failed: {e:#}")}),',
'''
if old not in text:
    raise SystemExit("escaped Rust json replacement block not found")
p.write_text(text.replace(old, new, 1))
