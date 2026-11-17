"""Add five hours of fake readings in one minute. Run with uv run simulate.py."""
from datetime import timedelta
from pathlib import Path
import math
import time

import duckdb

ROOT = Path(__file__).parent
database = ROOT / "hvac.duckdb"
if not database.exists():
    raise SystemExit("Run uv run main.py first, then press Enter to close its session.")

con = duckdb.connect(str(database))
try:
    con.execute("SET TimeZone = 'UTC'")
    try:
        last = con.execute("SELECT MAX(time) FROM nf.data").fetchone()[0]
    except duckdb.CatalogException:
        raise SystemExit("Run uv run main.py first to create the tables and load data.") from None
    if last is None:
        raise SystemExit("Run uv run main.py first to load the example readings.")
    rule = (ROOT / "fault_rule.sql").read_text(encoding="utf-8")

    print("Adding readings every second. Running the SQL rule every 10 seconds.")
    print("AHU-1 warms after 20 seconds. AHU-2 stays near 13 C.")
    print("Stops after 60 seconds. Ctrl+C also stops it.")
    for tick in range(60):
        stamp = last + timedelta(minutes=5 * (tick + 1))
        samples = []
        for ahu in ("AHU-1", "AHU-2"):
            warm = ahu == "AHU-1" and tick >= 20
            sat_c = round((19.0 if warm else 13.0) + 0.2 * math.sin(tick), 2)
            samples.append((f"{ahu}/sat", stamp, sat_c))
            samples.append((f"{ahu}/cooling_enabled", stamp, 1.0))
            print(f"{stamp:%H:%M} UTC  {ahu}  SAT {sat_c:.1f} C", flush=True)

        # Store both AHUs' readings for this timestamp together.
        con.execute("BEGIN TRANSACTION")
        con.executemany("INSERT INTO nf.data VALUES (?, ?, ?)", samples)
        con.execute("COMMIT")

        if tick % 10 == 9:
            con.execute(rule)
            rows = con.execute("""
                SELECT equipment_id, status, fault_samples
                FROM fdd.rule_result
                WHERE window_end = (SELECT MAX(window_end) FROM fdd.rule_result)
                ORDER BY equipment_id
            """).fetchall()
            for equipment, status, faults in rows:
                print(f"  SQL result  {equipment}  {status}  fault samples {faults}", flush=True)
        time.sleep(1)
except KeyboardInterrupt:
    print("Simulation stopped.")
finally:
    con.close()

print("Reopen the browser with uv run main.py")

