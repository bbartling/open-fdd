#!/usr/bin/env python3
from pathlib import Path

p = Path("scripts/pr2_equipment_type_patch.py")
text = p.read_text()
start_marker = "# append_package_json success: turn expression arm into block and sync registry\n"
end_marker = "# 3) FDD inventory/results prefer persisted stamps.\n"
start = text.find(start_marker)
end = text.find(end_marker)
if start < 0 or end < 0 or end <= start:
    raise SystemExit("append/re-ingest transformer section not found")
# Persistence is established on the canonical full-package import. Keep append and
# role-editor re-ingest behavior out of this PR; root sidecar retention can be
# hardened separately if those flows ever replace the building cache wholesale.
text = text[:start] + end_marker + text[end + len(end_marker):]
p.write_text(text)
