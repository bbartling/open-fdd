# Learn HVAC fault detection with DuckDB

Load fake AHU readings, explore them in a browser, and run a small SQL fault rule.
Python runs DuckDB on your computer. The browser displays its tables and query results.

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and internet access for dependency installation and the browser interface assets.
Queries and data stay local. See the [DuckDB UI documentation](https://duckdb.org/docs/2.0/core_extensions/ui).

## 1. Load the data and open the browser

Open PowerShell in this folder. From an Open-FDD checkout, first run
`cd tutorials/duckdb_browser_afdd`.

```powershell
uv run main.py
```

The browser opens at http://localhost:4213. Keep PowerShell running.
The first run loads seven days of readings for two AHUs, sampled every five minutes.
There are four points and **8,064 stored samples**. Reopening preserves your data.

| Object | What it holds |
| --- | --- |
| `nf.data` | Raw point IDs, timestamps, and measured values |
| `fdd.point` | Each point's AHU and role |
| `fdd.input_sample` | A view joining those two tables, so readings have AHU names and roles |
| `fdd.rule_result` | The SQL rule's saved assessments |

`nf` and `fdd` are schemas, which group database objects. A table stores rows.
A view runs a saved query whenever you read it. This view adds labels to the stored readings.

Temperatures are **degrees Celsius**, and timestamps use **UTC**.
`cooling_enabled` is a fake mode signal with values 0 and 1.
The example uses its own small schema and a teaching rule inspired by Open-FDD.

## 2. Read the tables

Create a SQL notebook in the DuckDB browser and run each query.

Count the samples. Expect `8064` before the simulator runs.

```sql
SELECT COUNT(*) AS samples FROM nf.data;
```

Find the four points and their AHUs.

```sql
SELECT * FROM fdd.point ORDER BY equipment_id, role;
```

Read temperature values using their mapped role.

```sql
SELECT equipment_id, ts, value AS sat_c
FROM fdd.input_sample
WHERE role = 'discharge_air_temperature'
ORDER BY ts DESC, equipment_id
LIMIT 12;
```

To explore the full temperature trend, remove `LIMIT 12` and sort by `ts` ascending.
If the UI offers a chart control, select a line chart using `ts` and `sat_c`.

## 3. Run the simulation

Press **Enter in PowerShell** to close the database session. Then run

```powershell
uv run simulate.py
```

Each real second adds five simulated minutes. AHU-1 warms to about 19 C after
20 seconds. AHU-2 stays near 13 C. Cooling is enabled on both AHUs.
Every ten seconds, Python executes `fault_rule.sql`. The simulation stops after
one minute. Ctrl+C stops it earlier.

The rule flags each sample where `sat_c > 16` and cooling is enabled.
Any flagged sample makes the hour `FAULT`. An hour with complete readings and
zero flagged samples is `PASS`. No usable temperature and cooling-enable pairs
at matching timestamps gives `NOT_ASSESSED` and `NULL` fault samples.
Production rules also evaluate confirmation time,
coverage, and verified equipment operation.

Reopen the browser.

```powershell
uv run main.py
```

Inspect the latest assessments.

```sql
SELECT equipment_id, status, fault_samples
FROM fdd.rule_result
WHERE window_end = (SELECT MAX(window_end) FROM fdd.rule_result)
ORDER BY equipment_id;
```

After a full simulation with the original threshold, expect

| equipment_id | status | fault_samples |
| --- | --- | --- |
| AHU-1 | FAULT | 12 |
| AHU-2 | PASS | 0 |

`fault_samples` counts flagged five-minute readings in that assessment's hour.
Successive hourly windows overlap, so adding their counts double-counts readings.

## 4. Change one line of SQL

Press Enter in PowerShell. Open `fault_rule.sql` and change

```sql
WHERE sat_c > 16 AND cooling_enabled = 1
```

to

```sql
WHERE sat_c > 20 AND cooling_enabled = 1
```

Run `uv run main.py` again. It recalculates the same latest hour using the new
threshold. Repeat the results query. Both AHUs now show `PASS` and `0`.
Restore `16` when finished. Older assessments retain their earlier values.

## Find the code

| File | Job |
| --- | --- |
| `main.py` | Create tables, load the CSV once, run the rule, open the browser |
| `simulate.py` | Add fake readings and run the SQL on a schedule |
| `schema.sql` | Define the tables and joining view |
| `fault_rule.sql` | Read, evaluate, and save one assessment per AHU |
| `week_history.csv` | The initial seven days of fake readings |
| `pyproject.toml` | Python requirements, including DuckDB 2.0.1 |

Use one script at a time. If the browser does not open automatically, visit
http://localhost:4213 while `main.py` is running. To reset, close both scripts,
delete the generated `hvac.duckdb` file, and run `uv run main.py`.

Continue with the [Open-FDD pandas and SQL parity tutorial](https://github.com/bbartling/open-fdd/tree/master/tutorials/duckdb_sql_parity)
to compare actual Open-FDD SQL rules with their pandas reference calculations.

