import sqlite3
import pandas as pd
from rdflib import Graph, Namespace
import time
from open_fdd.air_handling_unit.faults import FaultConditionOne

PERCENTAGE_COLS_TO_CONVERT = [
    "Supply_Fan_VFD_Speed_Sensor",  # BRICK formatted column name
]

# Minimal config dict just for fc1
config_dict_template = {
    "INDEX_COL_NAME": "timestamp",
    "DUCT_STATIC_COL": "Supply_Air_Static_Pressure_Sensor",
    "DUCT_STATIC_SETPOINT_COL": "Supply_Air_Static_Pressure_Setpoint",
    "SUPPLY_VFD_SPEED_COL": "Supply_Fan_VFD_Speed_Sensor",
    "VFD_SPEED_PERCENT_ERR_THRES": 0.05,
    "VFD_SPEED_PERCENT_MAX": 0.99,
    "DUCT_STATIC_INCHES_ERR_THRES": 0.1,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": 10,
}


def load_rdf_graph(file_path):
    print("Loading RDF graph...")
    g = Graph()
    g.parse(file_path, format="turtle")
    return g


def run_sparql_query(graph):
    print("Running SPARQL query...")
    query = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX ref: <https://brickschema.org/schema/Reference#>

    SELECT ?ahu ?sensorType ?sensor WHERE {
        ?ahu brick:hasPoint ?sensor .
        ?sensor a ?sensorType .
        FILTER (?sensorType IN (brick:Supply_Air_Static_Pressure_Sensor, brick:Supply_Air_Static_Pressure_Setpoint, brick:Supply_Fan_VFD_Speed_Sensor))
    }
    """
    return graph.query(query)


def extract_sensor_data(query_result):
    print("SPARQL query completed. Checking results...")
    sensor_data = {}
    for row in query_result:
        ahu = str(row.ahu).split("/")[-1]
        sensor_type = str(row.sensorType).split("#")[-1]
        sensor_data.setdefault(ahu, {})[sensor_type] = row.sensor
        print(f"Found sensor for {ahu}: {sensor_type} -> {row.sensor}")
    return sensor_data


def retrieve_timeseries_data(sensor_data, conn):
    dfs = []
    for ahu, sensors in sensor_data.items():
        print(f"Querying SQLite for AHU: {ahu}")
        df_ahu = None
        for sensor_type, sensor_uri in sensors.items():
            sensor_id = sensor_uri.split("/")[-1]
            print(f"Querying SQLite for sensor: {sensor_id} of type: {sensor_type}")
            sql_query = """
            SELECT timestamp, value
            FROM TimeseriesData
            WHERE sensor_name = ?
            """
            df_sensor = pd.read_sql_query(sql_query, conn, params=(sensor_id,))
            if df_sensor.empty:
                print(
                    f"No data found for sensor: {sensor_type} with sensor_id: {sensor_id}"
                )
            else:
                print(
                    f"Data found for sensor: {sensor_type}, number of records: {len(df_sensor)}"
                )
                df_sensor = df_sensor.rename(columns={"value": sensor_type})
                if df_ahu is None:
                    df_ahu = df_sensor.set_index("timestamp")
                else:
                    df_ahu = pd.merge(
                        df_ahu,
                        df_sensor.set_index("timestamp"),
                        left_index=True,
                        right_index=True,
                    )
        if df_ahu is not None:
            dfs.append((ahu, df_ahu))
    return dfs


def convert_floats(df, columns):
    for column in columns:
        df[column] = df[column] / 100.0
    print(df.head())
    return df


def run_fault_one(config_dict, df):
    fc1 = FaultConditionOne(config_dict)
    df = fc1.apply(df)
    print(f"Total faults detected: {df['fc1_flag'].sum()}")
    return df


def update_fault_flags_in_db(df, conn, batch_size=1000):
    cursor = conn.cursor()
    update_data = [(int(row["fc1_flag"]), index) for index, row in df.iterrows()]

    start_time = time.time()
    print("Starting batch update...")

    for i in range(0, len(update_data), batch_size):
        print(f"Doing batch {i}")
        batch = update_data[i : i + batch_size]
        cursor.executemany(
            """
            UPDATE TimeseriesData
            SET fc1_flag = ?
            WHERE timestamp = ?
            """,
            batch,
        )
        conn.commit()

        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print(
            f"Batch {i//batch_size + 1} completed: {len(batch)} records updated in {int(minutes)} minutes and {int(seconds)} seconds"
        )

    print("Batch update completed.")
    total_records = len(update_data)
    total_time = time.time() - start_time
    records_per_minute = total_records / (total_time / 60)
    print(f"Total records updated: {total_records}")
    print(
        f"Total time taken: {int(total_time // 60)} minutes and {int(total_time % 60)} seconds"
    )
    print(f"Records per minute: {records_per_minute:.2f}")


def main():
    # Step 1: Load the RDF graph from the Turtle file
    g = load_rdf_graph("brick_model_with_timeseries.ttl")

    # Step 2: Run SPARQL query to find AHUs and their sensors
    rdf_result = run_sparql_query(g)

    # Step 3: Extract sensor data from SPARQL query result
    sensor_data = extract_sensor_data(rdf_result)

    # Step 4: Connect to SQLite database
    print("Connecting to SQLite database...")
    conn = sqlite3.connect("brick_timeseries.db")

    # Step 5: Retrieve timeseries data from the database for each AHU
    ahu_dataframes = retrieve_timeseries_data(sensor_data, conn)

    # Process each AHU separately
    for ahu, df_combined in ahu_dataframes:
        print(f"Processing data for AHU: {ahu}")

        if df_combined is not None:
            # Step 6: Convert analog outputs to floats
            df_combined = convert_floats(df_combined, PERCENTAGE_COLS_TO_CONVERT)

            # Step 7: Customize config_dict for each AHU
            config_dict = config_dict_template.copy()

            # Step 8: Run fault condition one
            df_combined = run_fault_one(config_dict, df_combined)

            # Step 9: Write the fault flags back to the database
            update_fault_flags_in_db(df_combined, conn)

            print(f"columns for {ahu}: \n", df_combined.columns)

    # Close the database connection
    conn.close()


if __name__ == "__main__":
    main()
