import pandas as pd
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
import sys


class FaultConditionOne(FaultCondition):
    """Class provides the definitions for Fault Condition 1.
    AHU low duct static pressure fan fault.
    """

    def __init__(
        self,
        brick_graph,
        column_mapping,
        troubleshoot_mode=False,
        rolling_window_size=10,
    ):
        self.brick_graph = brick_graph
        self.column_mapping = column_mapping  # Now passed as an argument
        self.troubleshoot_mode = troubleshoot_mode
        self.rolling_window_size = rolling_window_size

        # Placeholder for attributes, these will be assigned dynamically
        self.duct_static_col = None
        self.supply_vfd_speed_col = None
        self.duct_static_setpoint_col = None

        # Set default error thresholds and maximums
        self.vfd_speed_percent_err_thres = 0.05
        self.vfd_speed_percent_max = 0.99
        self.duct_static_inches_err_thres = 0.1

        # Assign the attributes by mapping URIs to DataFrame column names
        self.assign_attributes()

    def assign_attributes(self):
        # Use the full URIs in the queries
        duct_static_sensors = self.find_entities_of_type(
            "https://brickschema.org/schema/1.1/Brick#Supply_Air_Static_Pressure_Sensor"
        )
        vfd_speed_sensors = self.find_entities_of_type(
            "https://brickschema.org/schema/1.1/Brick#Supply_Fan_VFD_Speed_Sensor"
        )
        static_pressure_setpoints = self.find_entities_of_type(
            "https://brickschema.org/schema/1.1/Brick#Static_Pressure_Setpoint"
        )

        # Debugging print statements to check what's found
        print("Duct Static Sensors found:", duct_static_sensors)
        print("VFD Speed Sensors found:", vfd_speed_sensors)
        print("Static Pressure Setpoints found:", static_pressure_setpoints)

        if not (
            duct_static_sensors and vfd_speed_sensors and static_pressure_setpoints
        ):
            raise ValueError("Required sensors are missing from the Brick model.")

        # Assuming you want to map the first found instance to the corresponding column
        self.duct_static_col = self.column_mapping.get(
            str(duct_static_sensors[0]), None
        )
        self.supply_vfd_speed_col = self.column_mapping.get(
            str(vfd_speed_sensors[0]), None
        )
        self.duct_static_setpoint_col = self.column_mapping.get(
            str(static_pressure_setpoints[0]), None
        )

        # Debugging print statements to check the column mapping results
        print("Mapped duct_static_col:", self.duct_static_col)
        print("Mapped supply_vfd_speed_col:", self.supply_vfd_speed_col)
        print("Mapped duct_static_setpoint_col:", self.duct_static_setpoint_col)

        sys.stdout.flush()

        # Raise an error if any of the columns were not mapped correctly
        if None in [
            self.duct_static_col,
            self.supply_vfd_speed_col,
            self.duct_static_setpoint_col,
        ]:
            raise ValueError("Column mapping failed for one or more sensors.")

    def find_entities_of_type(self, brick_class_uri):
        query = f"""
        SELECT ?s WHERE {{
            ?s rdf:type <{brick_class_uri}> .
        }}
        """
        results = self.brick_graph.query(query)
        entities = [row.s for row in results]
        if not entities:
            print(f"No entities found for type: {brick_class_uri}")
        return entities

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            print(
                "Troubleshoot mode enabled - additional debug information will be printed."
            )
            sys.stdout.flush()
            self.troubleshoot_cols(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col]
        self.check_analog_pct(df, columns_to_check)

        df["static_check_"] = (
            df[self.duct_static_col]
            < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres
        )
        df["fan_check_"] = (
            df[self.supply_vfd_speed_col]
            >= self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres
        )

        # Combined condition check
        df["combined_check"] = df["static_check_"] & df["fan_check_"]

        # Rolling sum to count consecutive trues
        rolling_sum = (
            df["combined_check"].rolling(window=self.rolling_window_size).sum()
        )
        # Set flag to 1 if rolling sum equals the window size
        df["fc1_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

        if not self.troubleshoot_mode:
            # Remove helper columns if not in troubleshoot mode
            del df["static_check_"]
            del df["fan_check_"]
            del df["combined_check"]
        else:
            print("Troubleshoot mode: retaining helper columns for debugging.")
            sys.stdout.flush()

        return df
