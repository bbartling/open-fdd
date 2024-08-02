import pandas as pd
import os
from open_fdd.air_handling_unit.faults.fault_condition_four import FaultConditionFour
from open_fdd.air_handling_unit.reports.report_fc4 import FaultCodeFourReport
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

# Load your data
ahu_data = r"C:\Users\bbartling\Documents\WPCRC_Master_Mod.csv"
df = pd.read_csv(ahu_data)

# Convert the timestamp column to datetime and set it as the index
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

# Print the DataFrame and its columns to verify
print(df)
print(df.columns)

# Configuration dictionary
config_dict = {
    # used for report name
    'AHU_NAME': "MZVAV_1",

    # timestamp column name
    'INDEX_COL_NAME': "timestamp",

    'DUCT_STATIC_COL': "SaStatic",
    'DUCT_STATIC_SETPOINT_COL': "SaStaticSPt",
    'SUPPLY_VFD_SPEED_COL': "Sa_FanSpeed",
    'MAT_COL': "MA_Temp",
    'OAT_COL': "OaTemp",
    'SAT_COL': "SaTempSP",
    'RAT_COL': "RaTemp",
    'HEATING_SIG_COL': "HW_Valve",  
    'COOLING_SIG_COL': "CW_Valve",  
    'ECONOMIZER_SIG_COL': "OA_Damper",
    'SUPPLY_FAN_AIR_VOLUME_COL': "vav_total_flow",

    'SAT_SETPOINT_COL': "SaTempSPt",
    'CONSTANT_LEAVE_TEMP_SP': False,
    'CONSTANT_LEAVE_TEMP_SP_VAL': 55.0,

    'VFD_SPEED_PERCENT_ERR_THRES': 0.05,
    'VFD_SPEED_PERCENT_MAX': 0.99,
    'DUCT_STATIC_INCHES_ERR_THRES': 0.1,
    'OUTDOOR_DEGF_ERR_THRES': 5.0,
    'MIX_DEGF_ERR_THRES': 5.0,
    'RETURN_DEGF_ERR_THRES': 2.0,
    'SUPPLY_DEGF_ERR_THRES': 2.0,
    'DELTA_T_SUPPLY_FAN': 2.0,

    'DELTA_OS_MAX': 7,
    'AHU_MIN_OA_DPR': 0.20,
    'OAT_RAT_DELTA_MIN': 10,
    'AIRFLOW_ERR_THRES': 0.3,
    'AHU_MIN_OA_CFM_DESIGN': 2500,
    'TROUBLESHOOT_MODE': True,
    'ROLLING_WINDOW_SIZE': 5
}

# Convert percentage columns to floats between 0 and 1
percentage_columns = [
    config_dict['SUPPLY_VFD_SPEED_COL'],
    config_dict['HEATING_SIG_COL'],
    config_dict['COOLING_SIG_COL'],
    config_dict['ECONOMIZER_SIG_COL']
]

for col in percentage_columns:
    df[col] = df[col] / 100.0

# Print out values to verify conversion
print(df['Sa_FanSpeed'].describe())
print(df['Sa_FanSpeed'].head(10))

# Check for non-finite values
if df['Sa_FanSpeed'].isnull().any():
    print("NaN values found in Sa_FanSpeed")
if (df['Sa_FanSpeed'] == float('inf')).any():
    print("Infinity values found in Sa_FanSpeed")
if (df['Sa_FanSpeed'] == -float('inf')).any():
    print("-Infinity values found in Sa_FanSpeed")

# Apply rolling average if needed for high frequency 1-minute or less data set
helper = HelperUtils()
df = helper.apply_rolling_average_if_needed(df)

fc4 = FaultConditionFour(config_dict)
df_fc4 = fc4.apply(df.copy())

df_fc4['fc4_flag'] = df_fc4['fc4_flag']

# Make reports in one month batches
df_fc4['month'] = df_fc4.index.to_period('M')
unique_months = df_fc4['month'].unique()

# Generate the report for each month
current_dir = os.path.dirname(os.path.abspath(__file__))

print("df cols: ",df.columns)

for month in unique_months:
    df_month = df_fc4[df_fc4['month'] == month].copy()

    fc4_dir = os.path.join(current_dir, "reports", "fault_code_4", str(month))

    os.makedirs(fc4_dir, exist_ok=True)

    # Generate report for Fault Condition Four
    report_fc4 = FaultCodeFourReport(config_dict)
    report_name_fc4 = f"ahu1_fc4_{month}.docx"
    report_fc4.create_report(fc4_dir, df_month, report_name=report_name_fc4)
