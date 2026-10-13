#!/usr/bin/env python3
"""Seed BUILDING_50 weather dry_bulb_f → weather.web_oa_t (lab Soft-OPEN)."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import psycopg

URL = os.environ["OPENFDD_DATABASE_URL"]
PATH = Path(os.environ.get("OPENFDD_WEATHER_CSV", "/weather/history_wide.csv"))


def main() -> int:
    buf = io.StringIO()
    w = csv.writer(buf)
    n = 0
    with PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            ts = rec.get("timestamp_utc")
            raw = rec.get("dry_bulb_f")
            if not ts or raw in (None, ""):
                continue
            try:
                val = float(raw)
            except ValueError:
                continue
            w.writerow([ts, "BUILDING_50", "weather.web_oa_t", "weather", val])
            n += 1
    buf.seek(0)
    with psycopg.connect(URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO site(site_id, dis, timezone, enabled) VALUES (%s, %s, %s, true) ON CONFLICT DO NOTHING",
            ("BUILDING_50", "BUILDING_50", "UTC"),
        )
        cur.execute(
            "INSERT INTO building(building_id, site_id, dis, timezone) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            ("BUILDING_50", "BUILDING_50", "BUILDING_50", "UTC"),
        )
        cur.execute(
            "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            ("BUILDING_50", "weather", "weather"),
        )
        with cur.copy(
            "COPY sample (ts, site_id, openfdd_key, haystack_id, val) FROM STDIN WITH (FORMAT csv)"
        ) as copy:
            copy.write(buf.read())
        cur.execute(
            "INSERT INTO role_map(building_id, equipment_id, openfdd_key, role) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            ("BUILDING_50", "weather", "weather.web_oa_t", "web_oa_t"),
        )
        conn.commit()
    print("weather.web_oa_t", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
