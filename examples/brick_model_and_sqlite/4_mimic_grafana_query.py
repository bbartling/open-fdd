import sqlite3
import pandas as pd
import matplotlib.pyplot as plt


def query_timeseries_data(conn, start_time=None, end_time=None):
    query = """
    SELECT timestamp, sensor_name, value, fc1_flag
    FROM TimeseriesData
    WHERE sensor_name IN ('Supply_Air_Static_Pressure_Sensor', 'Supply_Air_Static_Pressure_Setpoint', 'Supply_Fan_VFD_Speed_Sensor')
    """

    if start_time and end_time:
        query += f" AND timestamp BETWEEN '{start_time}' AND '{end_time}'"

    df = pd.read_sql_query(query, conn)
    print(f"Retrieved {len(df)} records from the database.")

    # Pivot the data to get one column per sensor
    df_pivot = df.pivot(index="timestamp", columns="sensor_name", values="value")
    df_pivot["fc1_flag"] = df["fc1_flag"]

    return df_pivot


def plot_timeseries(df, output_file=None):
    plt.figure(figsize=(14, 7))

    # Plot each sensor's data
    for column in df.columns:
        if column != "fc1_flag":
            plt.plot(df.index, df[column], label=column)

    # Highlight the times when a fault was detected
    fault_times = df.index[df["fc1_flag"] == 1]
    plt.scatter(
        fault_times,
        [df.loc[time, "Supply_Air_Static_Pressure_Sensor"] for time in fault_times],
        color="red",
        label="Fault Detected",
        zorder=5,
    )

    plt.title("HVAC Timeseries Data")
    plt.xlabel("Timestamp")
    plt.ylabel("Value")
    plt.legend()
    plt.grid(True)

    if output_file:
        plt.savefig(output_file)
        print(f"Plot saved as {output_file}")
    else:
        plt.show()


def main():
    # Step 1: Connect to the SQLite database
    conn = sqlite3.connect("brick_timeseries.db")

    # Step 2: Query the timeseries data
    df = query_timeseries_data(conn)

    # Step 3: Plot the data
    plot_timeseries(df, output_file="timeseries_plot.png")

    # Close the connection
    conn.close()


if __name__ == "__main__":
    main()
