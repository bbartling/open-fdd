import matplotlib.pyplot as plt
import pandas as pd
import sqlite3
import matplotlib.dates as mdates


def plot_timeseries(df, filename="mimic_grafana_plot.png"):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 10))
    fig.suptitle("HVAC Timeseries Data and Fault Detection")

    # Plot Static Pressure Sensor and Setpoint on ax1
    ax1.plot(df.index, df["SaStatic"], label="Static Pressure Sensor")
    ax1.plot(df.index, df["SaStaticSPt"], label="Static Pressure Setpoint")
    ax1.legend(loc="best")
    ax1.set_ylabel("Inch WC")
    # ax1.grid(True)

    # Improve timestamp formatting for ax1
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
    fig.autofmt_xdate(rotation=45)  # Rotate the labels for better readability

    # Plot Fan Speed on ax2
    ax2.plot(df.index, df["Sa_FanSpeed"], color="g", label="Fan Speed")
    ax2.legend(loc="best")
    ax2.set_ylabel("Fan Speed (%)")
    # ax2.grid(True)

    # Improve timestamp formatting for ax2
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))

    # Plot Fault Flag on ax3
    ax3.plot(df.index, df["fc1_flag"], label="Fault Detected", color="k")
    ax3.set_xlabel("Timestamp")
    ax3.set_ylabel("Fault Flags")
    ax3.legend(loc="best")
    # ax3.grid(True)

    # Improve timestamp formatting for ax3
    ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))

    # Rotate x-axis labels for all subplots to improve readability
    fig.autofmt_xdate(rotation=45)

    # Save the plot to a file
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(filename)
    plt.close()


def query_timeseries_data(conn, start_time=None, end_time=None):
    query = """
    SELECT timestamp, sensor_name, value, fc1_flag
    FROM TimeseriesData
    WHERE sensor_name IN ('Sa_FanSpeed', 'SaStatic', 'SaStaticSPt')
    """

    if start_time and end_time:
        query += f" AND timestamp BETWEEN '{start_time}' AND '{end_time}'"

    df = pd.read_sql_query(query, conn)
    print(f"Retrieved {len(df)} records from the database.")

    # Convert the 'timestamp' column to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Pivot the data to get one column per sensor
    df_pivot = df.pivot_table(index="timestamp", columns="sensor_name", values="value")

    # Add the fc1_flag back to the pivoted DataFrame, aligned with the timestamp
    df_pivot["fc1_flag"] = df.groupby("timestamp")["fc1_flag"].first()

    # Set the 'timestamp' as the index
    df_pivot = df_pivot.set_index(df_pivot.index)

    return df_pivot


def main():
    # Step 1: Connect to the SQLite database
    conn = sqlite3.connect("brick_timeseries.db")

    # Step 2: Query the timeseries data
    df = query_timeseries_data(conn)
    print(df)
    print(df.columns)

    # Step 3: Plot the data
    plot_timeseries(df)

    # Close the connection
    conn.close()


if __name__ == "__main__":
    main()
