"""Build a tiny demo openfdd_package_v1 zip for Cloud testing."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo_package_v1.zip"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    hist = "timestamp_utc,fan_status,oa_t,sat\n"
    for i in range(12):
        hist += f"2024-06-01T12:{i:02d}:00Z,1,70,{55 + i % 3}\n"
    files = {
        "manifest.json": json.dumps(
            {
                "schema_version": "openfdd_package_v1",
                "building_id": "DEMO_CLOUD",
                "grid_minutes": 5,
                "timezone": "UTC",
                "notes": "Synthetic non-sensitive demo",
            },
            indent=2,
        ),
        "session_config.json": json.dumps(
            {
                "schema_version": "openfdd_session_v1",
                "unit_system": "imperial",
                "prefer_web_oat": True,
                "chw_leave_max_f": 48.0,
                "role_map": {
                    "AHU_1": {
                        "fan-status": "fan-status",
                        "outside-air-temp": "outside-air-temp",
                        "discharge-air-temp": "discharge-air-temp",
                    }
                },
            },
            indent=2,
        ),
        "AHU_1/history_wide.csv": hist,
        "AHU_1/columns.csv": "col,point_role\nfan_status,fan_status\noa_t,oa_t\nsat,sat\n",
        "weather/history_wide.csv": "timestamp_utc,oa_t\n"
        + "\n".join(f"2024-06-01T12:{i:02d}:00Z,{70 + i}" for i in range(12))
        + "\n",
    }
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
