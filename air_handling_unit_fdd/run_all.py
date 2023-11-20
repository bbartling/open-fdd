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

AHU_NAME = run_all_config.AHU_NAME
INDEX_COL_NAME = run_all_config.INDEX_COL_NAME
DUCT_STATIC_COL = run_all_config.DUCT_STATIC_COL
DUCT_STATIC_SETPOINT_COL = run_all_config.DUCT_STATIC_SETPOINT_COL
SUPPLY_VFD_SPEED_COL = run_all_config.SUPPLY_VFD_SPEED_COL
MIX_AIR_TEMP_COL = run_all_config.MIX_AIR_TEMP_COL
OUTSIDE_AIR_TEMP_COL = run_all_config.OUTSIDE_AIR_TEMP_COL
SUPPLY_AIR_TEMP_COL = run_all_config.SUPPLY_AIR_TEMP_COL
RETURN_AIR_TEMP_COL = run_all_config.RETURN_AIR_TEMP_COL
HEAT_VALVE_COMMAND_COL = run_all_config.HEAT_VALVE_COMMAND_COL
COOL_VALVE_COMMAND_COL = run_all_config.COOL_VALVE_COMMAND_COL
OUTSIDE_AIR_DAMPER_COMMAND_COL = run_all_config.OUTSIDE_AIR_DAMPER_COMMAND_COL
SUPPLY_FAN_AIR_VOLUME_COL = run_all_config.SUPPLY_FAN_AIR_VOLUME_COL
SUPPLY_AIR_TEMP_SETPOINT_COL = run_all_config.SUPPLY_AIR_TEMP_SETPOINT_COL
CONSTANT_LEAVE_TEMP_SP = run_all_config.CONSTANT_LEAVE_TEMP_SP
CONSTANT_LEAVE_TEMP_SP_VAL = run_all_config.CONSTANT_LEAVE_TEMP_SP_VAL
VFD_SPEED_PERCENT_ERR_THRES = run_all_config.VFD_SPEED_PERCENT_ERR_THRES
VFD_SPEED_PERCENT_MAX = run_all_config.VFD_SPEED_PERCENT_MAX
DUCT_STATIC_PRESS_ERR_THRES = run_all_config.DUCT_STATIC_PRESS_ERR_THRES
OUTSIDE_AIR_TEMP_ERR_THRES = run_all_config.OUTSIDE_AIR_TEMP_ERR_THRES
MIX_AIR_TEMP_ERR_THRES = run_all_config.MIX_AIR_TEMP_ERR_THRES
RETURN_AIR_TEMP_ERR_THRES = run_all_config.RETURN_AIR_TEMP_ERR_THRES
SUPPLY_AIR_TEMP_ERR_THRES = run_all_config.SUPPLY_AIR_TEMP_ERR_THRES
FAN_DELTA_TEMP_ERR_THRES = run_all_config.FAN_DELTA_TEMP_ERR_THRES
DELTA_OS_MAX = run_all_config.DELTA_OS_MAX
AHU_MIN_OA = run_all_config.AHU_MIN_OA
DELTA_TEMP_MIN = run_all_config.DELTA_TEMP_MIN
AIRFLOW_ERR_THRES = run_all_config.AIRFLOW_ERR_THRES
AHU_DESIGN_OA = run_all_config.AHU_DESIGN_OA
TROUBLESHOOT_MODE = run_all_config.TROUBLESHOOT_MODE


def fault_applier(_fc, df):
    return _fc.apply(df)

def report_maker(report, counter, df):
    print("report maker called", report, counter)
    report_name = f"{AHU_NAME}_fc{str(counter)}_report"
    document = report.create_report(report_name, df)
    path = os.path.join(os.path.curdir, "final_report")
    if not os.path.exists(path):
        os.makedirs(path)
    document.save(os.path.join(path, f"{report_name}.docx"))
    print(f"Success on report maker {report_name}")
    return counter + 1  # Update the counter and return the updated value


def apply_faults_and_generate_reports(df, to_do):
    _fc1 = FaultConditionOne(
        VFD_SPEED_PERCENT_ERR_THRES,
        VFD_SPEED_PERCENT_MAX,
        DUCT_STATIC_PRESS_ERR_THRES,
        DUCT_STATIC_COL,
        SUPPLY_VFD_SPEED_COL,
        DUCT_STATIC_SETPOINT_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc1_report = FaultCodeOneReport(
        VFD_SPEED_PERCENT_ERR_THRES,
        VFD_SPEED_PERCENT_MAX,
        DUCT_STATIC_PRESS_ERR_THRES,
        DUCT_STATIC_COL,
        SUPPLY_VFD_SPEED_COL,
        DUCT_STATIC_SETPOINT_COL,
        API_KEY,
    )

    _fc2 = FaultConditionTwo(
        MIX_AIR_TEMP_ERR_THRES,
        RETURN_AIR_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc2_report = FaultCodeTwoReport(
        MIX_AIR_TEMP_ERR_THRES,
        RETURN_AIR_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        API_KEY,
    )

    _fc3 = FaultConditionThree(
        MIX_AIR_TEMP_ERR_THRES,
        RETURN_AIR_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc3_report = FaultCodeThreeReport(
        MIX_AIR_TEMP_ERR_THRES,
        RETURN_AIR_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        API_KEY,
    )

    _fc4 = FaultConditionFour(
        DELTA_OS_MAX,
        AHU_MIN_OA,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        HEAT_VALVE_COMMAND_COL,
        COOL_VALVE_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc4_report = FaultCodeFourReport(DELTA_OS_MAX, API_KEY)

    _fc5 = FaultConditionFive(
        MIX_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        FAN_DELTA_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_COL,
        HEAT_VALVE_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc5_report = FaultCodeFiveReport(
        MIX_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        FAN_DELTA_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_COL,
        HEAT_VALVE_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
    )

    _fc6 = FaultConditionSix(
        AIRFLOW_ERR_THRES,
        AHU_DESIGN_OA,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        RETURN_AIR_TEMP_ERR_THRES,
        DELTA_TEMP_MIN,
        AHU_MIN_OA,
        SUPPLY_FAN_AIR_VOLUME_COL,
        MIX_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        HEAT_VALVE_COMMAND_COL,
        COOL_VALVE_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc6_report = FaultCodeSixReport(
        SUPPLY_FAN_AIR_VOLUME_COL,
        MIX_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        RETURN_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
    )

    _fc7 = FaultConditionSeven(
        SUPPLY_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        HEAT_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc7_report = FaultCodeSevenReport(
        SUPPLY_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        HEAT_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
    )

    _fc8 = FaultConditionEight(
        FAN_DELTA_TEMP_ERR_THRES,
        MIX_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        AHU_MIN_OA,
        MIX_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        COOL_VALVE_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc8_report = FaultCodeEightReport(
        MIX_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
    )

    _fc9 = FaultConditionNine(
        FAN_DELTA_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        AHU_MIN_OA,
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        OUTSIDE_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc9_report = FaultCodeNineReport(
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        OUTSIDE_AIR_TEMP_COL,
        SUPPLY_VFD_SPEED_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
    )

    _fc10 = FaultConditionTen(
        OUTSIDE_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_ERR_THRES,
        MIX_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc10_report = FaultCodeTenReport(
        MIX_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
    )

    _fc11 = FaultConditionEleven(
        FAN_DELTA_TEMP_ERR_THRES,
        OUTSIDE_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc11_report = FaultCodeElevenReport(
        SUPPLY_AIR_TEMP_COL,
        OUTSIDE_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
    )

    _fc12 = FaultConditionTwelve(
        FAN_DELTA_TEMP_ERR_THRES,
        MIX_AIR_TEMP_ERR_THRES,
        SUPPLY_AIR_TEMP_ERR_THRES,
        AHU_MIN_OA,
        SUPPLY_AIR_TEMP_COL,
        MIX_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc12_report = FaultCodeTwelveReport(
        SUPPLY_AIR_TEMP_COL,
        MIX_AIR_TEMP_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
    )

    _fc13 = FaultConditionThirteen(
        SUPPLY_AIR_TEMP_ERR_THRES,
        AHU_MIN_OA,
        SUPPLY_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        troubleshoot=TROUBLESHOOT_MODE,
    )

    _fc13_report = FaultCodeThirteenReport(
        SUPPLY_AIR_TEMP_COL,
        SUPPLY_AIR_TEMP_SETPOINT_COL,
        COOL_VALVE_COMMAND_COL,
        OUTSIDE_AIR_DAMPER_COMMAND_COL,
        SUPPLY_VFD_SPEED_COL,
    )

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

    df = pd.read_csv(args.input, index_col=INDEX_COL_NAME, parse_dates=True)
    time_diff = df.index.to_series().diff().iloc[1:]
    max_diff = time_diff.max()

    if max_diff > pd.Timedelta(minutes=5):
        print(
            f"Warning: Maximum time difference between consecutive timestamps is {max_diff}."
        )
        print("SKIPPING 5 MINUTE ROLLING AVERAGE COMPUTATION OF DATA")
    else:
        df = df.rolling("5T").mean()

    if CONSTANT_LEAVE_TEMP_SP:
        df[SUPPLY_AIR_TEMP_SETPOINT_COL] = CONSTANT_LEAVE_TEMP_SP_VAL

    # Apply fault conditions and generate reports
    apply_faults_and_generate_reports(df, to_do=args.do)
