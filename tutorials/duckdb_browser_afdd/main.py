"""Load the example data, run the rule, and open DuckDB. Run with uv run main.py."""
from pathlib import Path
import duckdb

ROOT = Path(__file__).parent
con = duckdb.connect(str(ROOT / "hvac.duckdb"))
con.execute("SET TimeZone = 'UTC'")
con.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))

# Seed the database once (one row per sensor per 5 minutes).
for ahu in ("AHU-1", "AHU-2"):
    for role in ("discharge_air_temperature", "cooling_enabled"):
        con.execute("INSERT INTO fdd.point VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    [f"{ahu}/{role}", ahu, role])

if con.execute("SELECT COUNT(*) FROM nf.data").fetchone()[0] == 0:
    path = str(ROOT / "week_history.csv")
    con.execute("""
        INSERT INTO nf.data
        SELECT equipment_id || '/discharge_air_temperature', timestamp::TIMESTAMPTZ, discharge_air_temperature
        FROM read_csv_auto(?, header=true)
        UNION ALL
        SELECT equipment_id || '/cooling_enabled', timestamp::TIMESTAMPTZ,
               CASE WHEN cooling_enabled THEN 1.0 ELSE 0.0 END
        FROM read_csv_auto(?, header=true)
    """, [path, path])
    print("Loaded seven days of fake AHU trends.")

# Reopening also recalculates the latest hour after you edit the SQL threshold.
con.execute((ROOT / "fault_rule.sql").read_text(encoding="utf-8"))
print("Assessed the latest simulated hour. All temperatures are Celsius and times are UTC.")
print("Explore nf.data, fdd.point, fdd.input_sample and fdd.rule_result.")
print("Browser: http://localhost:4213")
try:
    con.execute("CALL start_ui()")
    input("Press Enter to close the browser session... ")
finally:
    con.close()
