import sqlite3
import pandas as pd
import re

# Step 1: Connect to SQLite database (or create it)
conn = sqlite3.connect("brick_timeseries.db")
cursor = conn.cursor()

# Step 2: Create tables for timeseries data and metadata
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS TimeseriesData (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    value REAL NOT NULL,
    fc1_flag INTEGER DEFAULT 0  -- Add this line to store fault condition 1 flags
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS TimeseriesReference (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeseries_id TEXT NOT NULL,
    stored_at TEXT NOT NULL
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS DatabaseStorage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    connstring TEXT NOT NULL
)
"""
)

# Step 3: Insert database metadata (SQLite reference)
cursor.execute(
    """
INSERT INTO DatabaseStorage (label, connstring)
VALUES
    ('SQLite Timeseries Storage', 'sqlite:///brick_timeseries.db')
"""
)

# Step 4: Load the CSV data
csv_file = r"C:\Users\bbartling\Documents\brick_data_July_2024.csv"
df = pd.read_csv(csv_file)
print("Original df.columns", df.columns)

# Ensure that the 'timestamp' column is properly parsed as a datetime object
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
else:
    raise ValueError("The CSV file does not contain a 'timestamp' column.")

# Step 4.1: Remove specific strings from the tail of the sensor names using regex
pattern = (
    r"(\/|inwc|\(\)|galmin|\(%\)|\(°F\)|\(A\)|\(Δpsi\)|\(cfm\)|\(in\/wc\)|\(gal\/min\))"
)
df.columns = df.columns.str.replace(pattern, "", regex=True)

# Print columns after modification to verify changes
print("Modified df.columns", df.columns)

# Step 5: Insert CSV data into the TimeseriesData table
for column in df.columns:
    if column != "timestamp":  # Skip the timestamp column itself
        # Only process columns related to AHU fan VFD speed, static pressure sensor, and setpoint
        if "StaticSPt" in column or "SaStatic" in column or "SaFanSpeedAO" in column:
            for index, row in df.iterrows():
                cursor.execute(
                    """
                INSERT INTO TimeseriesData (sensor_name, timestamp, value)
                VALUES (?, ?, ?)
                """,
                    (
                        column,
                        row["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                        row[column],
                    ),
                )
                if index < 5:  # Print the first 5 rows only
                    print(
                        f"Inserted sensor name {column} with value {row[column]} at {row['timestamp']}"
                    )
            print(f"Processed {column} in step 5")
        else:
            pass

conn.commit()

print("Starting step 6")

# Step 6: Insert timeseries references based on sensor names
for column in df.columns:
    if column != "timestamp":  # Skip the timestamp column itself
        # Only process columns related to AHU fan VFD speed, static pressure sensor, and setpoint
        if "StaticSPt" in column or "SaStatic" in column or "SaFanSpeedAO" in column:
            cursor.execute(
                """
            INSERT INTO TimeseriesReference (timeseries_id, stored_at)
            VALUES (?, ?)
            """,
                (column, "SQLite Timeseries Storage"),
            )
            print(f"Inserted reference for {column} in step 6")
        else:
            pass

conn.commit()

print("Step 6 is done")

# Close the connection
conn.close()

print("SQLite database created and populated with CSV data.")
