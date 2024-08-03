import pandas as pd
import os
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
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

from config import config_dict

fault_counts = {}

def process_fault_conditions(df, config_dict):

    helper = HelperUtils()

    # Apply rolling average if needed for
    # high frequency 1-minute or less data set
    df = helper.apply_rolling_average_if_needed(df)

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

    # Apply fault conditions to DataFrame
    df_fc1 = fc1.apply(df.copy())
    fc1_faults = df_fc1["fc1_flag"].sum()
    print("fc1 done... fault sum: ",fc1_faults)
    fault_counts["fc1_fault_sum"] = fc1_faults
    
    df_fc2 = fc2.apply(df.copy())
    fc2_faults = df_fc2["fc2_flag"].sum()
    print("fc2 done... fault sum: ",fc2_faults)
    fault_counts["fc2_fault_sum"] = fc2_faults
    
    df_fc3 = fc3.apply(df.copy())
    fc3_faults = df_fc3["fc3_flag"].sum()
    print("fc3 done... fault sum: ",fc3_faults)
    fault_counts["fc3_fault_sum"] = fc3_faults
    
    df_fc4 = fc4.apply(df.copy())  # Fault 4 with special handling
    fc4_faults = df_fc4["fc4_flag"].sum()
    print("fc4 done... fault sum: ",fc4_faults)
    fault_counts["fc4_fault_sum"] = fc4_faults
    
    df_fc5 = fc5.apply(df.copy())
    fc5_faults = df_fc5["fc5_flag"].sum()
    print("fc5 done... fault sum: ",fc5_faults)
    fault_counts["fc5_fault_sum"] = fc5_faults
    
    if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None:
        df_fc6 = fc6.apply(df.copy())
        fc6_faults = df_fc6["fc6_flag"].sum()
        print("fc6 done... fault sum: ",fc6_faults)
        fault_counts["fc6_fault_sum"] = fc6_faults

    df_fc7 = fc7.apply(df.copy())
    fc7_faults = df_fc7["fc7_flag"].sum()
    print("fc7 done... fault sum: ",fc7_faults)
    fault_counts["fc7_fault_sum"] = fc7_faults
    
    df_fc8 = fc8.apply(df.copy())
    fc8_faults = df_fc8["fc8_flag"].sum()
    print("fc8 done... fault sum: ",fc8_faults)
    fault_counts["fc8_fault_sum"] = fc8_faults
    
    df_fc9 = fc9.apply(df.copy())
    fc9_faults = df_fc9["fc9_flag"].sum()
    print("fc9 done... fault sum: ",fc9_faults)
    fault_counts["fc9_fault_sum"] = fc9_faults
    
    df_fc10 = fc10.apply(df.copy())
    fc10_faults = df_fc10["fc10_flag"].sum()
    print("fc10 done... fault sum: ",fc10_faults)
    fault_counts["fc10_fault_sum"] = fc10_faults
    
    df_fc11 = fc11.apply(df.copy())
    fc11_faults = df_fc11["fc11_flag"].sum()
    print("fc11 done... fault sum: ",fc11_faults)
    fault_counts["fc11_fault_sum"] = fc11_faults
    
    df_fc12 = fc12.apply(df.copy())
    fc12_faults = df_fc12["fc12_flag"].sum()
    print("fc12 done... fault sum: ",fc12_faults)
    fault_counts["fc12_fault_sum"] = fc12_faults
    
    # Combine fault condition results
    df_combined = df_fc1.copy()
    df_combined["fc2_flag"] = df_fc2["fc2_flag"]
    df_combined["fc3_flag"] = df_fc3["fc3_flag"]
    df_combined["fc5_flag"] = df_fc5["fc5_flag"]

    if config_dict["SUPPLY_FAN_AIR_VOLUME_COL"] is not None:
        df_combined["fc6_flag"] = df_fc6["fc6_flag"]

    df_combined["fc7_flag"] = df_fc7["fc7_flag"]
    df_combined["fc8_flag"] = df_fc8["fc8_flag"]
    df_combined["fc9_flag"] = df_fc9["fc9_flag"]
    df_combined["fc10_flag"] = df_fc10["fc10_flag"]
    df_combined["fc11_flag"] = df_fc11["fc11_flag"]
    df_combined["fc12_flag"] = df_fc12["fc12_flag"]

    # Print the number of faults for each condition
    for key, value in fault_counts.items():
        print(f"{key}: {value}")
    print("=" * 50)

    # Save fault counts to CSV
    fault_counts_df = pd.DataFrame(
        list(fault_counts.items()), columns=["Fault Condition", "Count"]
    )
    fault_counts_df.to_csv("fault_counts.csv", index=False)

    return df_combined


if __name__ == "__main__":
    # Load your data
    ahu_data = r"C:\Users\bbartling\Documents\WPCRC_Master_Mod.csv"
    df = pd.read_csv(ahu_data)

    # this data the AO's are floats between 0.0 and 100
    # so convert to percentage for floats between 0 and 1
    # so code under the hood understands it
    percentage_columns = [
        config_dict["SUPPLY_VFD_SPEED_COL"],
        config_dict["HEATING_SIG_COL"],
        config_dict["COOLING_SIG_COL"],
        config_dict["ECONOMIZER_SIG_COL"],
    ]

    for col in percentage_columns:
        df[col] = df[col] / 100.0

    # Convert the timestamp column to datetime and set it as the index
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)

    # Print the DataFrame and its columns to verify
    print(df)
    print(df.columns)

    df_combined = process_fault_conditions(df, config_dict)
