import argparse
import os

import pandas as pd

from faults import FaultConditionEight
from reports import FaultCodeEightReport

# python 3.10 on Windows 10
# py .\fc8.py -i ./ahu_data/hvac_random_fake_data/fc8_fake_data1.csv -o fake1_ahu_fc8_report

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
DELTA_SUPPLY_FAN = 2
MIX_DEGF_ERR_THRES = 5
SUPPLY_DEGF_ERR_THRES = 2

# ADJUST this param for the AHU MIN OA damper stp
AHU_MIN_OA = 20

_fc8 = FaultConditionEight(
    DELTA_SUPPLY_FAN,
    MIX_DEGF_ERR_THRES,
    SUPPLY_DEGF_ERR_THRES,
    AHU_MIN_OA,
    "sat",
    "mat",
    "economizer_sig",
    "cooling_sig"
)


_fc8_report = FaultCodeEightReport(    
    "sat",
    "mat",
    "supply_vfd_speed",
    "economizer_sig"
)


df = pd.read_csv(args.input, index_col="Date", parse_dates=True).rolling("5T").mean()

start = df.head(1).index.date
print("Dataset start: ", start)

end = df.tail(1).index.date
print("Dataset end: ", end)

for col in df.columns:
    print("df column: ", col, "- max len: ", df[col].size)

# return a whole new dataframe with fault flag as new col
df2 = _fc8.apply(df)
print(df2.head())
print(df2.describe())


document = _fc8_report.create_report(args.output, df2)
path = os.path.join(os.path.curdir, "final_report")
if not os.path.exists(path):
    os.makedirs(path)
document.save(os.path.join(path, f"{args.output}.docx"))
