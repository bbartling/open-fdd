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

    def apply_rolling_average_if_needed(self, df, freq="1T", rolling_window="5T"):
        return SharedUtils.apply_rolling_average_if_needed(df, freq, rolling_window)

    def process_all_faults(self, df, config_dict):
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

        fault_counts = {}

        # Apply rolling average if needed for high frequency 1-minute or less data set
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

        # Optionally initialize Fault Condition Six
        fc6 = FaultConditionSix(config_dict) if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None else None

        # Function to apply a fault condition and collect its results
        def apply_fault_condition(fc, df, fault_flag_col):
            df_result = fc.apply(df)
            fault_sum = df_result[fault_flag_col].sum()
            print(f"{fc.__class__.__name__} done")
            print(f"Fault description here")
            print("fault sum:", fault_sum)
            print("=" * 50)
            sys.stdout.flush()
            return df_result, fault_sum

        # Apply each fault condition and store the results
        df_fc1, fc1_faults = apply_fault_condition(fc1, df, "fc1_flag")
        df_fc2, fc2_faults = apply_fault_condition(fc2, df, "fc2_flag")
        df_fc3, fc3_faults = apply_fault_condition(fc3, df, "fc3_flag")
        df_fc4, fc4_faults = apply_fault_condition(fc4, df, "fc4_flag")
        df_fc5, fc5_faults = apply_fault_condition(fc5, df, "fc5_flag")
        
        if fc6 is not None:
            df_fc6, fc6_faults = apply_fault_condition(fc6, df, "fc6_flag")
            fault_counts["fc6_fault_sum"] = fc6_faults

        df_fc7, fc7_faults = apply_fault_condition(fc7, df, "fc7_flag")
        df_fc8, fc8_faults = apply_fault_condition(fc8, df, "fc8_flag")
        df_fc9, fc9_faults = apply_fault_condition(fc9, df, "fc9_flag")
        df_fc10, fc10_faults = apply_fault_condition(fc10, df, "fc10_flag")
        df_fc11, fc11_faults = apply_fault_condition(fc11, df, "fc11_flag")
        df_fc12, fc12_faults = apply_fault_condition(fc12, df, "fc12_flag")

        # Store fault counts
        fault_counts["fc1_fault_sum"] = fc1_faults
        fault_counts["fc2_fault_sum"] = fc2_faults
        fault_counts["fc3_fault_sum"] = fc3_faults
        fault_counts["fc4_fault_sum"] = fc4_faults
        fault_counts["fc5_fault_sum"] = fc5_faults
        if fc6 is not None:
            fault_counts["fc6_fault_sum"] = fc6_faults
        fault_counts["fc7_fault_sum"] = fc7_faults
        fault_counts["fc8_fault_sum"] = fc8_faults
        fault_counts["fc9_fault_sum"] = fc9_faults
        fault_counts["fc10_fault_sum"] = fc10_faults
        fault_counts["fc11_fault_sum"] = fc11_faults
        fault_counts["fc12_fault_sum"] = fc12_faults

        # Combine fault condition results
        df_combined = df_fc1
        df_combined["fc2_flag"] = df_fc2["fc2_flag"]
        df_combined["fc3_flag"] = df_fc3["fc3_flag"]
        df_combined["fc5_flag"] = df_fc5["fc5_flag"]

        if fc6 is not None:
            df_combined["fc6_flag"] = df_fc6["fc6_flag"]

        df_combined["fc7_flag"] = df_fc7["fc7_flag"]
        df_combined["fc8_flag"] = df_fc8["fc8_flag"]
        df_combined["fc9_flag"] = df_fc9["fc9_flag"]
        df_combined["fc10_flag"] = df_fc10["fc10_flag"]
        df_combined["fc11_flag"] = df_fc11["fc11_flag"]
        df_combined["fc12_flag"] = df_fc12["fc12_flag"]

        # Save fault counts to CSV
        fault_counts_df = pd.DataFrame(
            list(fault_counts.items()), columns=["Fault Condition", "Count"]
        )

        return df_combined, df_fc4
