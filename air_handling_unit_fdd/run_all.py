import argparse
import os
import pandas as pd

from faults import *
from reports import *

from reports.open_ai_report_fc1 import FaultCodeOneReport
from reports.open_ai_report_fc2 import FaultCodeTwoReport
from reports.open_ai_report_fc3 import FaultCodeThreeReport
from reports.open_ai_report_fc4 import FaultCodeFourReport

from api_key import API_KEY
import run_all_config

# instead of explicitly naming the above vars, import the config variables from config file as a single dictionary
config_dict = run_all_config.config_dict

def fault_applier(_fc, df):
    return _fc.apply(df)

def report_maker(report, counter, df):
    print("report maker called", report, counter)
    report_name = f"{config_dict['AHU_NAME']}_fc{str(counter)}_report"
    document = report.create_report(report_name, df)
    path = os.path.join(os.path.curdir, "final_report")
    if not os.path.exists(path):
        os.makedirs(path)
    document.save(os.path.join(path, f"{report_name}.docx"))
    print(f"Success on report maker {report_name}")
    return counter + 1  # Update the counter and return the updated value


def apply_faults_and_generate_reports(df, to_do):

    _fc1 = FaultConditionOne(config_dict)
    _fc1_report = FaultCodeOneReport(config_dict, api_key=API_KEY)

    _fc2 = FaultConditionTwo(config_dict)
    _fc2_report = FaultCodeTwoReport(config_dict, api_key=API_KEY)

    _fc3 = FaultConditionThree(config_dict)
    _fc3_report = FaultCodeThreeReport(config_dict, api_key=API_KEY)

    _fc4 = FaultConditionFour(config_dict)
    _fc4_report = FaultCodeFourReport(config_dict, API_KEY)

    _fc5 = FaultConditionFive(config_dict)
    _fc5_report = FaultCodeFiveReport(config_dict)

    _fc6 = FaultConditionSix(config_dict)
    _fc6_report = FaultCodeSixReport(config_dict)

    _fc7 = FaultConditionSeven(config_dict)
    _fc7_report = FaultCodeSevenReport(config_dict)

    _fc8 = FaultConditionEight(config_dict)
    _fc8_report = FaultCodeEightReport(config_dict)

    _fc9 = FaultConditionNine(config_dict)
    _fc9_report = FaultCodeNineReport(config_dict)

    _fc10 = FaultConditionTen(config_dict)
    _fc10_report = FaultCodeTenReport(config_dict)

    _fc11 = FaultConditionEleven(config_dict)
    _fc11_report = FaultCodeElevenReport(config_dict)

    _fc12 = FaultConditionTwelve(config_dict)
    _fc12_report = FaultCodeTwelveReport(config_dict)

    _fc13 = FaultConditionThirteen(config_dict)
    _fc13_report = FaultCodeThirteenReport(config_dict)

    # Combine fault conditions and reports into tuples
    faults_and_reports = [
        (_fc1, _fc1_report),
        (_fc2, _fc2_report),
        (_fc3, _fc3_report),
        (_fc4, _fc4_report),
        (_fc5, _fc5_report),
        (_fc6, _fc6_report),
        (_fc7, _fc7_report),
        (_fc8, _fc8_report),
        (_fc9, _fc9_report),
        (_fc10, _fc10_report),
        (_fc11, _fc11_report),
        (_fc12, _fc12_report),
        (_fc13, _fc13_report),
    ]

    counter = 1  # Initialize the counter
    max_do = max(to_do)
    print("MAX DO:", max_do)
    print("TO DO: ", to_do)

    if max_do < 15 and to_do:
        indexes = [index - 1 for index in to_do]  # Convert to 0-based indexes
        for index in indexes:
            if 0 <= index < len(faults_and_reports):
                fault, report = faults_and_reports[index]
                print(f"Starting Fault Equation {index + 1}")
                try:
                    copied_df = df.copy()
                    df2 = fault.apply(copied_df)
                    print("Success on fault", index + 1)
                    counter = report_maker(report, counter, df2)  # Pass the counter and update its value
                    print("Success on report", index + 1)
                except Exception as e:
                    print(f"Error on fault rule {index + 1}! - {e}")
            else:
                print(f"Invalid tuple index: {index + 1}")
    else:
        print("Incorrect args, the maximum is 15 for -d")

    print("All Done...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    args = parser.add_argument_group("Options")
    args.add_argument("-i", "--input", required=True, type=str, help="CSV File Input")
    parser.add_argument(
        "-d",
        "--do",
        required=False,
        nargs="+",
        type=int,
        default=[],
        help="Fault(s) to do or run-only",
    )
    args = parser.parse_args()
    df = pd.read_csv(
        args.input,
        index_col=config_dict['INDEX_COL_NAME'],
        parse_dates=True
    )
    time_diff = df.index.to_series().diff().iloc[1:]
    max_diff = time_diff.max()

    if max_diff > pd.Timedelta(minutes=5):
        print(
            f"Warning: Maximum time difference between consecutive timestamps is {max_diff}."
        )
        print("SKIPPING 5 MINUTE ROLLING AVERAGE COMPUTATION OF DATA")
    else:
        df = df.rolling("5T").mean()

    if config_dict['CONSTANT_LEAVE_TEMP_SP']:
        df[config_dict['SUPPLY_AIR_TEMP_SETPOINT_COL']] = config_dict['CONSTANT_LEAVE_TEMP_SP_VAL']

    # Apply fault conditions and generate reports
    apply_faults_and_generate_reports(df, to_do=args.do)
