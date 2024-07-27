import pandas as pd
import os
from air_handling_unit.faults.fault_condition_one import FaultConditionOne
from air_handling_unit.reports.report_fc1 import FaultCodeOneReport

# Load your data
ahu_data = r"C:\Users\bbartling\Documents\WPCRC_Master.csv"
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
    'MIX_DEGF_ERR_THRES': 2.0,
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

# Apply fault conditions
fc1 = FaultConditionOne(config_dict)
df_faults = fc1.apply(df)

# Generate reports
current_dir = os.path.dirname(os.path.abspath(__file__))
report = FaultCodeOneReport(config_dict)
report.create_report(current_dir, df_faults)
