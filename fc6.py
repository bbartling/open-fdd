import argparse
import os

import pandas as pd

from faults import FaultConditionSix
from reports import FaultCodeSixReport

# python 3.10 on Windows 10
# py .\fc6.py -i ./ahu_data/hvac_random_fake_data/fc6_fake_data1.csv -o fake1_ahu_fc6_report
# py .\fc6.py -i ./ahu_data/ahu2.csv -o mnb_ahu2_fc6_report


parser = argparse.ArgumentParser(add_help=False)
args = parser.add_argument_group("Options")

args.add_argument(
    "-h", "--help", action="help", help="Show this help message and exit."
)
args.add_argument("-i", "--input", required=True, type=str, help="CSV File Input")
args.add_argument(
    "-o", "--output", required=True, type=str, help="Word File Output Name"
)
"""
FUTURE 
 * incorporate an arg for SI units 
 * °C on temp sensors
 * piping pressure sensor PSI conversion
 * air flow CFM conversion
 * AHU duct static pressure "WC

args.add_argument('--use-SI-units', default=False, action='store_true')
args.add_argument('--no-SI-units', dest='use-SI-units', action='store_false')
"""
args = parser.parse_args()

# G36 params shouldnt need adjusting
# error threshold parameters
OAT_DEGF_ERR_THRES = 5
RAT_DEGF_ERR_THRES = 2
DELTA_TEMP_MIN = 10
AIRFLOW_ERR_THRES = .3

# THIS G36 params NEEDs INPUT its for the OA
# ventilation setpoint. Most AHU systems will
# not have an air flow station with a trend log avail
# for vent setpoint but instead use a fixed OA setpoint
# that test & balance (TAB) contractor implements at
# building startup. Find blue print records or TAB
# report for what CFM setpoint the mechanical 
# engineer used to design the system. This param
# will be right in the mechanical schedule for 
# the AHU along with all other output params for
# how the AHU was sized to meet all the engineers
# mechanical requirements
AHU_MIN_CFM_DESIGN = 2500

# ADJUST this param for the AHU MIN OA damper stp
# To verify AHU is operating in Min OA OS1 & OS4 states only
AHU_MIN_OA_DPR = 20


_fc6 = FaultConditionSix(
    AIRFLOW_ERR_THRES,
    AHU_MIN_CFM_DESIGN,
    OAT_DEGF_ERR_THRES,
    RAT_DEGF_ERR_THRES,
    DELTA_TEMP_MIN,
    AHU_MIN_OA_DPR,
    "AHU2_SaFanFlow_value",
    "AHU2_MATemp",
    "HourlyDryBulbTemp",
    "AHU2_RATemp_value",
    "AHU2_SaFanSpeedAO_value",
    "AHU2_MA_RA_DamperAO",
    "heating_sig",
    "AHU2_CW_ValveAO",
    troubleshoot=False
)


_fc6_report = FaultCodeSixReport(
    "AHU2_SaFanFlow_value",
    "AHU2_MATemp",
    "HourlyDryBulbTemp",
    "AHU2_RATemp_value",
    "AHU2_SaFanSpeedAO_value"
)


df = pd.read_csv(args.input, index_col="Date", parse_dates=True).rolling("5T").mean()

df["heating_sig"] = 0

# weather data from a different source
oat = pd.read_csv('./ahu_data/oat.csv', index_col="Date", parse_dates=True).rolling("5T").mean()
df = oat.join(df)
df = df.ffill().bfill()
print(df)

start = df.head(1).index.date
print("Dataset start: ", start)

end = df.tail(1).index.date
print("Dataset end: ", end)

for col in df.columns:
    print("df column: ", col, "- max len: ", df[col].size)

# return a whole new dataframe with fault flag as new col
df2 = _fc6.apply(df)
print(df2.head())
print(df2.describe())
print(df2.columns)

#df.to_csv('fc6_troubleshoot.csv')

document = _fc6_report.create_report(args.output, df2)
path = os.path.join(os.path.curdir, "final_report")
if not os.path.exists(path):
    os.makedirs(path)
document.save(os.path.join(path, f"{args.output}.docx"))
