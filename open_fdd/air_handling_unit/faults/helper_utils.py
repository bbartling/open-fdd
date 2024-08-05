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
        if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None:
            fc6 = FaultConditionSix(config_dict)

        # Apply fault conditions to DataFrame and track memory usage
        df_fc1 = fc1.apply(df.copy())
        fc1_faults = df_fc1["fc1_flag"].sum()
        print("fc1 done")
        print("Duct static pressure too low with fan operating near max speed")
        print("fault sum: ", fc1_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc1_fault_sum"] = fc1_faults

        df_fc2 = fc2.apply(df.copy())
        fc2_faults = df_fc2["fc2_flag"].sum()
        print("fc2 done")
        print("Mix temp too low; should be between outside and return temp") 
        print("fault sum: ", fc2_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc2_fault_sum"] = fc2_faults

        df_fc3 = fc3.apply(df.copy())
        fc3_faults = df_fc3["fc3_flag"].sum()
        print("fc3 done")
        print("Mix temp too high; should be between outside and return temp")
        print("fault sum: ", fc3_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc3_fault_sum"] = fc3_faults

        df_fc4 = fc4.apply(df.copy())  # Fault 4 with special handling
        fc4_faults = df_fc4["fc4_flag"].sum()
        print("fc4 done")
        print("PID hunting; too many operating state changes per hour")
        print("fault sum: ", fc4_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc4_fault_sum"] = fc4_faults

        df_fc5 = fc5.apply(df.copy())
        fc5_faults = df_fc5["fc5_flag"].sum()
        print("fc5 done")
        print("Supply temp too low should be higher than mix temp")
        print("fault sum: ", fc5_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc5_fault_sum"] = fc5_faults

        if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None:
            df_fc6 = fc6.apply(df.copy())
            fc6_faults = df_fc6["fc6_flag"].sum()
            print("fc6 done")
            print("OA fraction too low or too high")
            print("fault sum: ", fc6_faults)
            print("=" * 50)
            sys.stdout.flush()
            fault_counts["fc6_fault_sum"] = fc6_faults

        df_fc7 = fc7.apply(df.copy())
        fc7_faults = df_fc7["fc7_flag"].sum()
        print("fc7 done")
        print("Supply temp too low in full heating")
        print("fault sum: ", fc7_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc7_fault_sum"] = fc7_faults

        df_fc8 = fc8.apply(df.copy())
        fc8_faults = df_fc8["fc8_flag"].sum()
        print("fc8 done")
        print("Supply and mix temp should be approx equal in econ mode")
        print("fault sum: ", fc8_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc8_fault_sum"] = fc8_faults

        df_fc9 = fc9.apply(df.copy())
        fc9_faults = df_fc9["fc9_flag"].sum()
        print("fc9 done")
        print("Outside temp too high in free cooling without additional mech cooling plus econ")
        print("fault sum: ", fc9_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc9_fault_sum"] = fc9_faults

        df_fc10 = fc10.apply(df.copy())
        fc10_faults = df_fc10["fc10_flag"].sum()
        print("fc10 done")
        print("Outdoor temp and mix temp should be approx equal in mech cooling plus econ")
        print("fault sum: ", fc10_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc10_fault_sum"] = fc10_faults

        df_fc11 = fc11.apply(df.copy())
        fc11_faults = df_fc11["fc11_flag"].sum()
        print("fc11 done")
        print("Outside temp too low for mech cooling plus econ")
        print("fault sum: ", fc11_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc11_fault_sum"] = fc11_faults

        df_fc12 = fc12.apply(df.copy())
        fc12_faults = df_fc12["fc12_flag"].sum()
        print("fc12 done")
        print("Supply temp too high should be less than mix temp in mech cooling plus econ")
        print("fault sum: ", fc12_faults)
        print("=" * 50)
        sys.stdout.flush()
        fault_counts["fc12_fault_sum"] = fc12_faults

        # Combine fault condition results
        df_combined = df_fc1.copy()
        del df_fc1
        df_combined["fc2_flag"] = df_fc2["fc2_flag"]
        del df_fc2
        df_combined["fc3_flag"] = df_fc3["fc3_flag"]
        del df_fc3
        df_combined["fc5_flag"] = df_fc5["fc5_flag"]
        del df_fc5

        if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None:
            df_combined["fc6_flag"] = df_fc6["fc6_flag"]
            del df_fc6

        df_combined["fc7_flag"] = df_fc7["fc7_flag"]
        del df_fc7
        df_combined["fc8_flag"] = df_fc8["fc8_flag"]
        del df_fc8
        df_combined["fc9_flag"] = df_fc9["fc9_flag"]
        del df_fc9
        df_combined["fc10_flag"] = df_fc10["fc10_flag"]
        del df_fc10
        df_combined["fc11_flag"] = df_fc11["fc11_flag"]
        del df_fc11
        df_combined["fc12_flag"] = df_fc12["fc12_flag"]
        del df_fc12

        '''
        # Print the number of faults for each condition
        for key, value in fault_counts.items():
            print(f"{key}: {value}")
            sys.stdout.flush()
        print("=" * 50)
        sys.stdout.flush()
        '''

        # Save fault counts to CSV
        fault_counts_df = pd.DataFrame(
            list(fault_counts.items()), columns=["Fault Condition", "Count"]
        )

        return df_combined, fault_counts_df
