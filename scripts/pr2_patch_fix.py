#!/usr/bin/env python3
from pathlib import Path

p = Path("scripts/pr2_equipment_type_patch.py")
text = p.read_text()
old = '''replace(
    p,
    "                    plant_signal_label(&cols),\\n                )\\n",
    "                    plant_signal_label(&cols),\\n                    &stamped_types,\\n                )\\n",
)
'''
new = '''sub(
    p,
    r"(plant_signal_label\\(&cols\\),\\n)(\\s*)\\)",
    r"\\1\\2&stamped_types,\\n\\2)",
)
'''
if old not in text:
    raise SystemExit("historian call-site transformer block not found")
p.write_text(text.replace(old, new, 1))
