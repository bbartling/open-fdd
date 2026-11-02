#!/usr/bin/env python3
"""Build a generic openfdd_package_v1 zip for CI static UI browser tests.

No fixture building ids — caller imports via POST /api/csv/import/package.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import zipfile

BUILDING_ID = "CI_STATIC_UI_SITE"
EQUIPMENT_ID = "EQ_AHU_01"
ROWS_DEFAULT = 288
PACKAGE_START = dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.timezone.utc)


def _validate_id(label: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
        raise ValueError(f"bad {label} {value!r}")


def _rows(n: int) -> list[dict[str, float | str]]:
    out: list[dict[str, float | str]] = []
    for i in range(n):
        ts = PACKAGE_START + dt.timedelta(minutes=5 * i)
        fan_on = 1.0 if (i % 12) < 8 else 0.0
        oa = 55.0 + (i % 24) * 0.5
        rat = 72.0 + (i % 10) * 0.2
        mat = rat + (oa - rat) * 0.25
        sat = 54.0 + (i % 8) * 0.15
        out.append(
            {
                "timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "OAT": round(oa, 2),
                "RAT": round(rat, 2),
                "MAT": round(mat, 2),
                "SAT": round(sat, 2),
                "SAT_SP": round(sat + 1.0, 2),
                "OA_DMP": round(40.0 + (i % 20), 1),
                "CLG_VLV": round((i % 30) * 2.0, 1),
                "HTG_VLV": round((i % 15) * 1.5, 1),
                "SF_SPD": round(55.0 + (i % 25), 1),
                "FAN_RUN": fan_on,
                "DA_P": round(0.85 + (i % 10) * 0.02, 3),
                "DA_P_SP": 1.0,
            }
        )
    return out


def package_zip(
    building_id: str = BUILDING_ID,
    equipment_id: str = EQUIPMENT_ID,
    rows: int = ROWS_DEFAULT,
) -> bytes:
    _validate_id("building_id", building_id)
    _validate_id("equipment_id", equipment_id)
    if rows < 48 or rows > 10_000:
        raise ValueError("rows out of bounds")

    manifest = {
        "schema_version": "openfdd_package_v1",
        "building_id": building_id,
        "grid_minutes": 5,
        "timezone": "UTC",
    }
    point_map = {
        "equipType": "ahu",
        "points": {
            "outside-air-temp": "OAT",
            "return-air-temp": "RAT",
            "mixed-air-temp": "MAT",
            "discharge-air-temp": "SAT",
            "discharge-air-temp-sp": "SAT_SP",
            "outside-air-damper": "OA_DMP",
            "cooling-valve": "CLG_VLV",
            "heating-valve": "HTG_VLV",
            "fan-cmd": "SF_SPD",
            "fan-status": "FAN_RUN",
            "duct-static-pressure": "DA_P",
            "duct-static-pressure-sp": "DA_P_SP",
        },
    }
    data = _rows(rows)
    cols = list(data[0].keys())
    csv_lines = [",".join(cols)]
    for row in data:
        csv_lines.append(",".join(str(row[c]) for c in cols))

    semantic_meta = {
        "schema": "openfdd_semantic_meta_v1",
        "building_id": building_id,
        "note": "CI static UI browser seed (synthetic, generic ids)",
        "equipment": [
            {
                "equipment_id": equipment_id,
                "display_name": "Synthetic AHU",
                "haystack_tags": ["ahu", "equip"],
            }
        ],
        "points": [
            {
                "equipment_id": equipment_id,
                "column": col,
                "haystack_tags": ["sensor", "point", "his"],
                "his": True,
            }
            for col in cols
            if col != "timestamp_utc"
        ],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        entries = (
            ("manifest.json", json.dumps(manifest, sort_keys=True)),
            ("semantic_meta.json", json.dumps(semantic_meta, sort_keys=True)),
            (f"{equipment_id}/history_wide.json", json.dumps(point_map, sort_keys=True)),
            (f"{equipment_id}/history_wide.csv", "\n".join(csv_lines) + "\n"),
        )
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Write zip to this path")
    parser.add_argument("--building", default=BUILDING_ID)
    parser.add_argument("--equipment", default=EQUIPMENT_ID)
    parser.add_argument("--rows", type=int, default=ROWS_DEFAULT)
    args = parser.parse_args()
    blob = package_zip(args.building, args.equipment, args.rows)
    with open(args.out, "wb") as fh:
        fh.write(blob)
    print(args.building)


if __name__ == "__main__":
    main()
