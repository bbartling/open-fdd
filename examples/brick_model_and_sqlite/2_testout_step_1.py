import sqlite3
import pandas as pd

# Connect to the SQLite database
conn = sqlite3.connect("brick_timeseries.db")

# Query the data
query = """
SELECT sensor_name, timestamp, value
FROM TimeseriesData
WHERE sensor_name = 'HWR_value'
ORDER BY timestamp ASC
"""
df = pd.read_sql_query(query, conn)

# Convert the timestamp column to datetime if needed
df["timestamp"] = pd.to_datetime(df["timestamp"])

# Set the 'timestamp' column as the index
df.set_index("timestamp", inplace=True)

# Pivot the DataFrame to make sensor_name the columns and value the data
df_pivot = df.pivot(columns="sensor_name", values="value")

# Display the DataFrame
print(df_pivot.head())
print()

# Display the DataFrame
print("SQL: ", df_pivot.describe())
print()

# Close the connection
conn.close()

# Just for fun see if the CSV file looks any different
csv_file = r"C:\Users\bbartling\Documents\WPCRC_July.csv"
df = pd.read_csv(csv_file)
print("CSV: ", df["HWR_value"].describe())
