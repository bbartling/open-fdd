import sys
from open_fdd.air_handling_unit.faults.shared_utils import SharedUtils
import pandas as pd

class HelperUtils:
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

    def process_all_faults(self, df, config_dict):
        # Import fault conditions
        from open_fdd.air_handling_unit.faults.fault_condition_one import FaultConditionOne
        from open_fdd.air_handling_unit.faults.fault_condition_two import FaultConditionTwo
        from open_fdd.air_handling_unit.faults.fault_condition_three import FaultConditionThree
        from open_fdd.air_handling_unit.faults.fault_condition_four import FaultConditionFour
        from open_fdd.air_handling_unit.faults.fault_condition_five import FaultConditionFive
        from open_fdd.air_handling_unit.faults.fault_condition_six import FaultConditionSix
        from open_fdd.air_handling_unit.faults.fault_condition_seven import FaultConditionSeven
        from open_fdd.air_handling_unit.faults.fault_condition_eight import FaultConditionEight
        from open_fdd.air_handling_unit.faults.fault_condition_nine import FaultConditionNine
        from open_fdd.air_handling_unit.faults.fault_condition_ten import FaultConditionTen
        from open_fdd.air_handling_unit.faults.fault_condition_eleven import FaultConditionEleven
        from open_fdd.air_handling_unit.faults.fault_condition_twelve import FaultConditionTwelve
        from open_fdd.air_handling_unit.faults.fault_condition_thirteen import FaultConditionThirteen
        from open_fdd.air_handling_unit.faults.fault_condition_fourteen import FaultConditionFourteen
        from open_fdd.air_handling_unit.faults.fault_condition_fifteen import FaultConditionFifteen

        fault_counts = {}

        # Apply rolling average if needed
        df = self.apply_rolling_average_if_needed(df)

        # Initialize Fault Condition Classes
        fc1 = FaultConditionOne(config_dict)
        fc2 = FaultConditionTwo(config_dict)
        fc3 = FaultConditionThree(config_dict)
        fc4 = FaultConditionFour(config_dict)
        fc5 = FaultConditionFive(config_dict)
        fc7 = FaultConditionSeven(config_dict)
        fc8 = FaultConditionEight(config_dict)
        fc9 = FaultConditionNine(config_dict)
        fc10 = FaultConditionTen(config_dict)
        fc11 = FaultConditionEleven(config_dict)
        fc12 = FaultConditionTwelve(config_dict)
        fc13 = FaultConditionThirteen(config_dict)

        # Optionally initialize Fault Condition Six
        fc6 = None
        if config_dict.get("SUPPLY_FAN_AIR_VOLUME_COL") is not None:
            fc6 = FaultConditionSix(config_dict)

        # Optionally initialize Fault Condition Fourteen
        fc14 = None
        if config_dict.get("COOLING_SIG_COL") is not None and config_dict.get("CLG_COIL_LEAVE_TEMP_COL") is not None:
            fc14 = FaultConditionFourteen(config_dict)

        # Optionally initialize Fault Condition Fifteen
        fc15 = None
        if config_dict.get("HTG_COIL_ENTER_TEMP_COL") is not None and config_dict.get("HTG_COIL_LEAVE_TEMP_COL") is not None:
            fc15 = FaultConditionFifteen(config_dict)

        # Apply fault conditions and calculate fault counts
        df_fc1 = fc1.apply(df.copy())
        fault_counts["fc1_fault_sum"] = df_fc1["fc1_flag"].sum()

        df_fc2 = fc2.apply(df.copy())
        fault_counts["fc2_fault_sum"] = df_fc2["fc2_flag"].sum()

        df_fc3 = fc3.apply(df.copy())
        fault_counts["fc3_fault_sum"] = df_fc3["fc3_flag"].sum()

        df_fc4 = fc4.apply(df.copy())
        fault_counts["fc4_fault_sum"] = df_fc4["fc4_flag"].sum()

        df_fc5 = fc5.apply(df.copy())
        fault_counts["fc5_fault_sum"] = df_fc5["fc5_flag"].sum()

        if fc6 is not None:
            df_fc6 = fc6.apply(df.copy())
            fault_counts["fc6_fault_sum"] = df_fc6["fc6_flag"].sum()

        df_fc7 = fc7.apply(df.copy())
        fault_counts["fc7_fault_sum"] = df_fc7["fc7_flag"].sum()

        df_fc8 = fc8.apply(df.copy())
        fault_counts["fc8_fault_sum"] = df_fc8["fc8_flag"].sum()

        df_fc9 = fc9.apply(df.copy())
        fault_counts["fc9_fault_sum"] = df_fc9["fc9_flag"].sum()

        df_fc10 = fc10.apply(df.copy())
        fault_counts["fc10_fault_sum"] = df_fc10["fc10_flag"].sum()

        df_fc11 = fc11.apply(df.copy())
        fault_counts["fc11_fault_sum"] = df_fc11["fc11_flag"].sum()

        df_fc12 = fc12.apply(df.copy())
        fault_counts["fc12_fault_sum"] = df_fc12["fc12_flag"].sum()

        df_fc13 = fc13.apply(df.copy())
        fault_counts["fc13_fault_sum"] = df_fc13["fc13_flag"].sum()

        if fc14 is not None:
            df_fc14 = fc14.apply(df.copy())
            fault_counts["fc14_fault_sum"] = df_fc14["fc14_flag"].sum()

        if fc15 is not None:
            df_fc15 = fc15.apply(df.copy())
            fault_counts["fc15_fault_sum"] = df_fc15["fc15_flag"].sum()

        # Combine fault condition results
        df_combined = df_fc1.copy()
        df_combined["fc2_flag"] = df_fc2["fc2_flag"]
        df_combined["fc3_flag"] = df_fc3["fc3_flag"]
        df_combined["fc4_flag"] = df_fc4["fc4_flag"]
        df_combined["fc5_flag"] = df_fc5["fc5_flag"]

        if fc6 is not None:
            df_combined["fc6_flag"] = df_fc6["fc6_flag"]

        df_combined["fc7_flag"] = df_fc7["fc7_flag"]
        df_combined["fc8_flag"] = df_fc8["fc8_flag"]
        df_combined["fc9_flag"] = df_fc9["fc9_flag"]
        df_combined["fc10_flag"] = df_fc10["fc10_flag"]
        df_combined["fc11_flag"] = df_fc11["fc11_flag"]
        df_combined["fc12_flag"] = df_fc12["fc12_flag"]
        df_combined["fc13_flag"] = df_fc13["fc13_flag"]

        if fc14 is not None:
            df_combined["fc14_flag"] = df_fc14["fc14_flag"]

        if fc15 is not None:
            df_combined["fc15_flag"] = df_fc15["fc15_flag"]

        # Save fault counts to CSV
        fault_counts_df = pd.DataFrame(
            list(fault_counts.items()), columns=["Fault Condition", "Count"]
        )

        return df_combined, df_fc4, fault_counts_df
