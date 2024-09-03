import sys
from open_fdd.air_handling_unit.faults.shared_utils import SharedUtils
import pandas as pd


class HelperUtils:

    def __init__(self):
        self.config_dict = None

    def set_config_dict(self, config_dict):
        self.config_dict = config_dict

    def clean_nan_values(self, df):
        return SharedUtils.clean_nan_values(df)

    def float_int_check_err(self, col):
        return SharedUtils.float_int_check_err(col)

    def float_max_check_err(self, col):
        return SharedUtils.float_max_check_err(col)

    def isfloat(self, num):
        return SharedUtils.isfloat(num)

    def isLessThanOnePointOne(self, num):
        return SharedUtils.isLessThanOnePointOne(num)

    def convert_to_float(self, df, col):
        return SharedUtils.convert_to_float(df, col)

    def apply_rolling_average_if_needed(self, df, freq="1min", rolling_window="5min"):
        return SharedUtils.apply_rolling_average_if_needed(df, freq, rolling_window)

    def validate_config(self, required_columns):
        """
        Check if all required columns are present and not None in the config dictionary.
        """
        if not self.config_dict:
            raise ValueError("Config dictionary is not set.")
        return all(self.config_dict.get(col) is not None for col in required_columns)

    def process_all_faults(self, df, config_dict):
        # Set the config dictionary
        self.set_config_dict(config_dict)

        from open_fdd.air_handling_unit.faults import (
            FaultConditionOne,
            FaultConditionTwo,
            FaultConditionThree,
            FaultConditionFour,
            FaultConditionFive,
            FaultConditionSix,
            FaultConditionSeven,
            FaultConditionEight,
            FaultConditionNine,
            FaultConditionTen,
            FaultConditionEleven,
            FaultConditionTwelve,
            FaultConditionThirteen,
            FaultConditionFourteen,
            FaultConditionFifteen,
        )

        fault_counts = {}

        # Apply rolling average if needed
        df = self.apply_rolling_average_if_needed(df)

        # Initialize Fault Condition Classes with necessary checks
        fc1 = None
        if self.validate_config(
            ["DUCT_STATIC_COL", "DUCT_STATIC_SETPOINT_COL", "SUPPLY_VFD_SPEED_COL"]
        ):
            print("Info: Running fc1")
            fc1 = FaultConditionOne(config_dict)
        else:
            print("Info: Skipping fc1")

        sys.stdout.flush()

        fc2 = None
        if self.validate_config(
            ["SUPPLY_VFD_SPEED_COL", "MAT_COL", "OAT_COL", "SAT_COL", "RAT_COL"]
        ):
            print("Info: Running fc2 Go!")
            fc2 = FaultConditionTwo(config_dict)
        else:
            print("Info: Skipping fc2")

        sys.stdout.flush()

        fc3 = None
        if self.validate_config(
            ["SUPPLY_VFD_SPEED_COL", "MAT_COL", "OAT_COL", "SAT_COL", "RAT_COL"]
        ):
            print("Info: Running fc3 Go!")
            fc3 = FaultConditionThree(config_dict)
        else:
            print("Info: Skipping fc3")

        sys.stdout.flush()

        fc4 = None
        if self.validate_config(
            [
                "SUPPLY_VFD_SPEED_COL",
                "COOLING_SIG_COL",
                "HEATING_SIG_COL",
                "ECONOMIZER_SIG_COL",
            ]
        ):
            print("Info: Running fc4 Go!")
            fc4 = FaultConditionFour(config_dict)
        else:
            print("Info: Skipping fc4")

        sys.stdout.flush()

        fc5 = None
        if self.validate_config(
            ["SUPPLY_VFD_SPEED_COL", "HEATING_SIG_COL", "SAT_COL", "MAT_COL"]
        ):
            print("Info: Running fc5 Go!")
            fc5 = FaultConditionFive(config_dict)
        else:
            print("Info: Skipping fc5")

        sys.stdout.flush()

        fc6 = None
        if self.validate_config(
            [
                "SUPPLY_VFD_SPEED_COL",
                "COOLING_SIG_COL",
                "HEATING_SIG_COL",
                "ECONOMIZER_SIG_COL",
                "SUPPLY_FAN_AIR_VOLUME_COL",
            ]
        ):
            print("Info: Running fc6 Go!")
            fc6 = FaultConditionSix(config_dict)
        else:
            print("Info: Skipping fc6")

        sys.stdout.flush()

        fc7 = None
        if self.validate_config(
            ["SUPPLY_VFD_SPEED_COL", "SAT_COL", "SAT_SETPOINT_COL", "HEATING_SIG_COL"]
        ):
            print("Info: Running fc7 Go!")
            fc7 = FaultConditionSeven(config_dict)
        else:
            print("Info: Skipping fc7")

        sys.stdout.flush()

        fc8 = None
        if self.validate_config(
            [
                "COOLING_SIG_COL",
                "ECONOMIZER_SIG_COL",
                "MAT_COL",
                "SUPPLY_VFD_SPEED_COL",
                "SAT_COL",
            ]
        ):
            print("Info: Running fc8 Go!")
            fc8 = FaultConditionEight(config_dict)
        else:
            print("Info: Skipping fc8")

        sys.stdout.flush()

        fc9 = None
        if self.validate_config(
            [
                "OAT_COL",
                "SUPPLY_VFD_SPEED_COL",
                "SAT_COL",
                "SAT_SETPOINT_COL",
                "COOLING_SIG_COL",
                "ECONOMIZER_SIG_COL",
            ]
        ):
            print("Info: Running fc9 Go!")
            fc9 = FaultConditionNine(config_dict)
        else:
            print("Info: Skipping fc9")

        sys.stdout.flush()

        fc10 = None
        if self.validate_config(
            [
                "MAT_COL",
                "OAT_COL",
                "SUPPLY_VFD_SPEED_COL",
                "COOLING_SIG_COL",
                "ECONOMIZER_SIG_COL",
            ]
        ):
            print("Info: Running fc10 Go!")
            fc10 = FaultConditionTen(config_dict)
        else:
            print("Info: Skipping fc10")

        sys.stdout.flush()

        fc11 = None
        if self.validate_config(
            [
                "OAT_COL",
                "SUPPLY_VFD_SPEED_COL",
                "COOLING_SIG_COL",
                "ECONOMIZER_SIG_COL",
                "SAT_SETPOINT_COL",
            ]
        ):
            print("Info: Running fc11 Go!")
            fc11 = FaultConditionEleven(config_dict)
        else:
            print("Info: Skipping fc11")

        sys.stdout.flush()

        fc12 = None
        if self.validate_config(
            [
                "SUPPLY_VFD_SPEED_COL",
                "ECONOMIZER_SIG_COL",
                "COOLING_SIG_COL",
                "SAT_COL",
                "MAT_COL",
            ]
        ):
            print("Info: Running fc12 Go!")
            fc12 = FaultConditionTwelve(config_dict)
        else:
            print("Info: Skipping fc12")

        sys.stdout.flush()

        fc13 = None
        if self.validate_config(
            [
                "SUPPLY_VFD_SPEED_COL",
                "ECONOMIZER_SIG_COL",
                "COOLING_SIG_COL",
                "SAT_SETPOINT_COL",
                "SAT_COL",
            ]
        ):
            print("Info: Running fc13 Go!")
            fc13 = FaultConditionThirteen(config_dict)
        else:
            print("Info: Skipping fc13")

        sys.stdout.flush()

        fc14 = None
        if (
            config_dict.get("COOLING_SIG_COL") is not None
            and config_dict.get("CLG_COIL_LEAVE_TEMP_COL") is not None
        ):
            print("Info: Running fc14 Go!")
            fc14 = FaultConditionFourteen(config_dict)
        else:
            print("Info: Skipping fc14")

        sys.stdout.flush()

        fc15 = None
        if (
            config_dict.get("HTG_COIL_ENTER_TEMP_COL") is not None
            and config_dict.get("HTG_COIL_LEAVE_TEMP_COL") is not None
        ):
            print("Info: Running fc15 Go!")
            fc15 = FaultConditionFifteen(config_dict)
        else:
            print("Info: Skipping fc15")

        sys.stdout.flush()

        # Apply fault conditions and calculate fault counts
        df_fc1 = fc1.apply(df.copy()) if fc1 is not None else None
        if df_fc1 is not None:
            fault_counts["fc1_fault_sum"] = df_fc1["fc1_flag"].sum()

        df_fc2 = fc2.apply(df.copy()) if fc2 is not None else None
        if df_fc2 is not None:
            fault_counts["fc2_fault_sum"] = df_fc2["fc2_flag"].sum()

        df_fc3 = fc3.apply(df.copy()) if fc3 is not None else None
        if df_fc3 is not None:
            fault_counts["fc3_fault_sum"] = df_fc3["fc3_flag"].sum()

        df_fc4 = fc4.apply(df.copy()) if fc4 is not None else pd.DataFrame()
        if not df_fc4.empty:
            fault_counts["fc4_fault_sum"] = df_fc4["fc4_flag"].sum()

        df_fc5 = fc5.apply(df.copy()) if fc5 is not None else None
        if df_fc5 is not None:
            fault_counts["fc5_fault_sum"] = df_fc5["fc5_flag"].sum()

        df_fc6 = fc6.apply(df.copy()) if fc6 is not None else None
        if df_fc6 is not None:
            fault_counts["fc6_fault_sum"] = df_fc6["fc6_flag"].sum()

        df_fc7 = fc7.apply(df.copy()) if fc7 is not None else None
        if df_fc7 is not None:
            fault_counts["fc7_fault_sum"] = df_fc7["fc7_flag"].sum()

        df_fc8 = fc8.apply(df.copy()) if fc8 is not None else None
        if df_fc8 is not None:
            fault_counts["fc8_fault_sum"] = df_fc8["fc8_flag"].sum()

        df_fc9 = fc9.apply(df.copy()) if fc9 is not None else None
        if df_fc9 is not None:
            fault_counts["fc9_fault_sum"] = df_fc9["fc9_flag"].sum()

        df_fc10 = fc10.apply(df.copy()) if fc10 is not None else None
        if df_fc10 is not None:
            fault_counts["fc10_fault_sum"] = df_fc10["fc10_flag"].sum()

        df_fc11 = fc11.apply(df.copy()) if fc11 is not None else None
        if df_fc11 is not None:
            fault_counts["fc11_fault_sum"] = df_fc11["fc11_flag"].sum()

        df_fc12 = fc12.apply(df.copy()) if fc12 is not None else None
        if df_fc12 is not None:
            fault_counts["fc12_fault_sum"] = df_fc12["fc12_flag"].sum()

        df_fc13 = fc13.apply(df.copy()) if fc13 is not None else None
        if df_fc13 is not None:
            fault_counts["fc13_fault_sum"] = df_fc13["fc13_flag"].sum()

        df_fc14 = fc14.apply(df.copy()) if fc14 is not None else None
        if df_fc14 is not None:
            fault_counts["fc14_fault_sum"] = df_fc14["fc14_flag"].sum()

        df_fc15 = fc15.apply(df.copy()) if fc15 is not None else None
        if df_fc15 is not None:
            fault_counts["fc15_fault_sum"] = df_fc15["fc15_flag"].sum()

        # Combine fault condition results
        df_combined = df_fc1.copy() if df_fc1 is not None else df.copy()

        if df_fc2 is not None:
            df_combined["fc2_flag"] = df_fc2["fc2_flag"]

        if df_fc3 is not None:
            df_combined["fc3_flag"] = df_fc3["fc3_flag"]

        # Skip combining df_fc4 since it is resampled

        if df_fc5 is not None:
            df_combined["fc5_flag"] = df_fc5["fc5_flag"]

        if df_fc6 is not None:
            df_combined["fc6_flag"] = df_fc6["fc6_flag"]

        if df_fc7 is not None:
            df_combined["fc7_flag"] = df_fc7["fc7_flag"]

        if df_fc8 is not None:
            df_combined["fc8_flag"] = df_fc8["fc8_flag"]

        if df_fc9 is not None:
            df_combined["fc9_flag"] = df_fc9["fc9_flag"]

        if df_fc10 is not None:
            df_combined["fc10_flag"] = df_fc10["fc10_flag"]

        if df_fc11 is not None:
            df_combined["fc11_flag"] = df_fc11["fc11_flag"]

        if df_fc12 is not None:
            df_combined["fc12_flag"] = df_fc12["fc12_flag"]

        if df_fc13 is not None:
            df_combined["fc13_flag"] = df_fc13["fc13_flag"]

        if df_fc14 is not None:
            df_combined["fc14_flag"] = df_fc14["fc14_flag"]

        if df_fc15 is not None:
            df_combined["fc15_flag"] = df_fc15["fc15_flag"]

        # Save fault counts to CSV
        fault_counts_df = pd.DataFrame(
            list(fault_counts.items()), columns=["Fault Condition", "Count"]
        )

        return df_combined, df_fc4, fault_counts_df
