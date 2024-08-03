import pandas as pd
import os

from open_fdd.air_handling_unit.reports.report_fc1 import FaultCodeOneReport
from open_fdd.air_handling_unit.reports.report_fc2 import FaultCodeTwoReport
from open_fdd.air_handling_unit.reports.report_fc3 import FaultCodeThreeReport
from open_fdd.air_handling_unit.reports.report_fc5 import FaultCodeFiveReport
from open_fdd.air_handling_unit.reports.report_fc6 import FaultCodeSixReport
from open_fdd.air_handling_unit.reports.report_fc7 import FaultCodeSevenReport
from open_fdd.air_handling_unit.reports.report_fc8 import FaultCodeEightReport
from open_fdd.air_handling_unit.reports.report_fc9 import FaultCodeNineReport
from open_fdd.air_handling_unit.reports.report_fc10 import FaultCodeTenReport
from open_fdd.air_handling_unit.reports.report_fc11 import FaultCodeElevenReport
from open_fdd.air_handling_unit.reports.report_fc12 import FaultCodeTwelveReport
from config import config_dict

def generate_reports(df_combined, unique_months, config_dict, fault_counts):
    current_dir = os.path.dirname(os.path.abspath(__file__))

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
            fault_sum_key = f"{flag_col.split('_')[0]}_fault_sum"
            if fault_counts.get(fault_sum_key, 0) > 0:
                if flag_col in df_month.columns and df_month[flag_col].sum() > 0:
                    report = report_class(config_dict)
                    report_name = f"ahu1_{flag_col.split('_')[0]}_{month}.docx"
                    report.create_report(dirs[dir_key], df_month, report_name=report_name)

if __name__ == "__main__":
    # Load your fault counts data
    fault_counts_csv_path = r"C:\Users\bbartling\Documents\fault_counts.csv"
    fault_counts_df = pd.read_csv(fault_counts_csv_path)
    fault_counts = dict(zip(fault_counts_df['Fault Condition'], fault_counts_df['Count']))

    # Load your data
    final_csv_path = r"C:\Users\bbartling\Documents\MZVAV_1_final.csv"
    df_combined = pd.read_csv(final_csv_path)

    # Convert the timestamp column to datetime and set it as the index
    df_combined["timestamp"] = pd.to_datetime(df_combined["timestamp"])
    df_combined.set_index("timestamp", inplace=True)

    # Process for unique months
    df_combined['month'] = df_combined.index.to_period('M')
    unique_months = df_combined['month'].unique()

    generate_reports(df_combined, unique_months, config_dict, fault_counts)
