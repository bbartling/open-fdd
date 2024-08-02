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
from open_fdd.air_handling_unit.reports.report_fc1 import FaultCodeOneReport
from open_fdd.air_handling_unit.reports.report_fc2 import FaultCodeTwoReport
from open_fdd.air_handling_unit.reports.report_fc3 import FaultCodeThreeReport
from open_fdd.air_handling_unit.reports.report_fc4 import FaultCodeFourReport
from open_fdd.air_handling_unit.reports.report_fc5 import FaultCodeFiveReport
from open_fdd.air_handling_unit.reports.report_fc6 import FaultCodeSixReport
from open_fdd.air_handling_unit.reports.report_fc7 import FaultCodeSevenReport
from open_fdd.air_handling_unit.reports.report_fc8 import FaultCodeEightReport
from open_fdd.air_handling_unit.reports.report_fc9 import FaultCodeNineReport
from open_fdd.air_handling_unit.reports.report_fc10 import FaultCodeTenReport
from open_fdd.air_handling_unit.reports.report_fc11 import FaultCodeElevenReport
from open_fdd.air_handling_unit.reports.report_fc12 import FaultCodeTwelveReport
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

def print_fault_counts(fault_counts, title="Number of faults for each condition:"):
    print("=" * 50)
    print(title)
    for key, value in fault_counts.items():
        print(f"{key}: {value}")
    print("=" * 50)

def process_fault_conditions(df, config_dict):
    # Convert percentage columns to floats between 0 and 1
    percentage_columns = [
        config_dict['SUPPLY_VFD_SPEED_COL'],
        config_dict['HEATING_SIG_COL'],
        config_dict['COOLING_SIG_COL'],
        config_dict['ECONOMIZER_SIG_COL']
    ]

    for col in percentage_columns:
        df[col] = df[col] / 100.0

    # Apply rolling average if needed for high frequency 1-minute or less data set
    helper = HelperUtils()
    df = helper.apply_rolling_average_if_needed(df)

    # Initialize dictionaries for fault count and DataFrame storage
    fault_counts = {}
    dfs = {}

    # Apply fault conditions and count flags
    fault_conditions = [
        FaultConditionOne(config_dict),
        FaultConditionTwo(config_dict),
        FaultConditionThree(config_dict),
        FaultConditionFour(config_dict),
        FaultConditionFive(config_dict),
        FaultConditionSeven(config_dict),
        FaultConditionEight(config_dict),
        FaultConditionNine(config_dict),
        FaultConditionTen(config_dict),
        FaultConditionEleven(config_dict),
        FaultConditionTwelve(config_dict)
    ]

    include_fc6 = config_dict['SUPPLY_FAN_AIR_VOLUME_COL'] is not None
    if include_fc6:
        fault_conditions.append(FaultConditionSix(config_dict))

    for i, fc in enumerate(fault_conditions, start=1):
        if i == 6 and not include_fc6:
            continue
        fault_flag = f'fc{i}_flag'
        df_fc = fc.apply(df.copy())
        if fault_flag in df_fc.columns:
            fault_counts[f'fc{i}'] = df_fc[fault_flag].sum()
            dfs[f'fc{i}'] = df_fc

    return dfs, fault_counts

def generate_reports(dfs, config_dict):
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Combine fault condition results
    df_combined = dfs['fc1'].copy()
    for i in range(2, 13):
        if i == 6 and 'fc6' not in dfs:
            continue
        fault_flag = f'fc{i}_flag'
        if fault_flag in dfs and fault_flag in dfs[f'fc{i}'].columns:
            df_combined[fault_flag] = dfs[f'fc{i}'][fault_flag]

    # Make reports in one month batches
    df_combined['month'] = df_combined.index.to_period('M')
    unique_months = df_combined['month'].unique()

    # Special handling for Fault Condition 4, as it involves resampled data
    df_fc4 = dfs['fc4']
    df_fc4['month'] = df_fc4.index.to_period('M')

    for month in unique_months:
        df_month = df_combined[df_combined['month'] == month].copy()

        # Skip the month if no faults are found
        if not df_month.filter(like='_flag').any().any():
            continue

        # Create directories for each fault type
        dirs = {
            'fc1_dir': os.path.join(current_dir, "reports", "fault_code_1", str(month)),
            'fc2_dir': os.path.join(current_dir, "reports", "fault_code_2", str(month)),
            'fc3_dir': os.path.join(current_dir, "reports", "fault_code_3", str(month)),
            'fc4_dir': os.path.join(current_dir, "reports", "fault_code_4", str(month)),
            'fc5_dir': os.path.join(current_dir, "reports", "fault_code_5", str(month)),
            'fc7_dir': os.path.join(current_dir, "reports", "fault_code_7", str(month)),
            'fc8_dir': os.path.join(current_dir, "reports", "fault_code_8", str(month)),
            'fc9_dir': os.path.join(current_dir, "reports", "fault_code_9", str(month)),
            'fc10_dir': os.path.join(current_dir, "reports", "fault_code_10", str(month)),
            'fc11_dir': os.path.join(current_dir, "reports", "fault_code_11", str(month)),
            'fc12_dir': os.path.join(current_dir, "reports", "fault_code_12", str(month))
        }

        if config_dict['SUPPLY_FAN_AIR_VOLUME_COL'] is not None:
            dirs['fc6_dir'] = os.path.join(current_dir, "reports", "fault_code_6", str(month))

        for dir_path in dirs.values():
            os.makedirs(dir_path, exist_ok=True)

        report_classes = [
            (FaultCodeOneReport, 'fc1_dir', 'fc1_flag'),
            (FaultCodeTwoReport, 'fc2_dir', 'fc2_flag'),
            (FaultCodeThreeReport, 'fc3_dir', 'fc3_flag'),
            (FaultCodeFiveReport, 'fc5_dir', 'fc5_flag'),
            (FaultCodeSevenReport, 'fc7_dir', 'fc7_flag'),
            (FaultCodeEightReport, 'fc8_dir', 'fc8_flag'),
            (FaultCodeNineReport, 'fc9_dir', 'fc9_flag'),
            (FaultCodeTenReport, 'fc10_dir', 'fc10_flag'),
            (FaultCodeElevenReport, 'fc11_dir', 'fc11_flag'),
            (FaultCodeTwelveReport, 'fc12_dir', 'fc12_flag')
        ]

        if config_dict['SUPPLY_FAN_AIR_VOLUME_COL'] is not None:
            report_classes.append((FaultCodeSixReport, 'fc6_dir', 'fc6_flag'))

        for report_class, dir_key, flag_col in report_classes:
            if flag_col in df_month.columns and df_month[flag_col].sum() > 0:
                report = report_class(config_dict)
                report_name = f"ahu1_{flag_col.split('_')[0]}_{month}.docx"
                report.create_report(dirs[dir_key], df_month, report_name=report_name)

        # Generate report for Fault Condition Four separately due to its resampled nature
        df_month_fc4 = df_fc4[df_fc4['month'] == month].copy()
        if 'fc4_flag' in df_month_fc4.columns and df_month_fc4['fc4_flag'].sum() > 0:
            report_fc4 = FaultCodeFourReport(config_dict)
            report_name_fc4 = f"ahu1_fc4_{month}.docx"
            report_fc4.create_report(dirs['fc4_dir'], df_month_fc4, report_name=report_name_fc4)

if __name__ == "__main__":
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
        'SUPPLY_FAN_AIR_VOLUME_COL': None,  # Set to None to skip FC6
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

    dfs, fault_counts = process_fault_conditions(df, config_dict)
    generate_reports(dfs, config_dict)

    # Print fault counts at the end
    print_fault_counts(fault_counts)
