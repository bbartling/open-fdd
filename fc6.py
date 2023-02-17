import argparse
import os

import pandas as pd

from faults import FaultConditionSix
from reports import FaultCodeSixReport

# python 3.10 on Windows 10
# py .\fc6.py -i ./ahu_data/hvac_random_fake_data/fc6_fake_data1.csv -o fake1_ahu_fc6_report

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

AHU_MIN_CFM_STP = 3000


# required inpouts are outside mix, and return air temperature
# AND calculated system air flow from totalizing all VAV 
# air flows or the supply fan AFMS in CFM

_fc6 = FaultConditionSix(
    AIRFLOW_ERR_THRES,
    AHU_MIN_CFM_STP,
    OAT_DEGF_ERR_THRES,
    RAT_DEGF_ERR_THRES,
    DELTA_TEMP_MIN,
    "vav_total_flow",
    "mat",
    "oat",
    "rat"
)


_fc6_report = FaultCodeSixReport("vav_total_flow")


df = pd.read_csv(args.input, index_col="Date", parse_dates=True).rolling("5T").mean()

start = df.head(1).index.date
print("Dataset start: ", start)

end = df.tail(1).index.date
print("Dataset end: ", end)

for col in df.columns:
    print("df column: ", col, "- max len: ", df[col].size)

# return a whole new dataframe with fault flag 6 as new col
df2 = _fc6.apply(df)
print(df2.head())
print(df2.describe())


document = _fc6_report.create_report(args.output, df2)
path = os.path.join(os.path.curdir, "final_report")
if not os.path.exists(path):
    os.makedirs(path)
document.save(os.path.join(path, f"{args.output}.docx"))
