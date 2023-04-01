import argparse
import os

import pandas as pd

from faults import FaultConditionFour
from reports import FaultCodeFourReport

# python 3.10 on Windows 10
# py .\fc4.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc4_report
# py .\fc4.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc4_report
# py .\fc4.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc4_report

parser = argparse.ArgumentParser(add_help=False)
args = parser.add_argument_group("Options")

args.add_argument(
    "-h", "--help", action="help", help="Show this help message and exit."
)

args.add_argument("-i", "--input", required=True,
                  type=str, help="CSV File Input")
args.add_argument(
    "-o", "--output", required=True, type=str, help="Word File Output Name"
)

args = parser.parse_args()

# G36 params COULD need adjusting
# default OS MAX state changes is 7
# which seems high, could be worth adjusting
# down to 4 to see what the faults look like
DELTA_OS_MAX = 7

# ADJUST this param for the AHU MIN OA damper stp
AHU_MIN_OA = .20


_fc4 = FaultConditionFour(
    DELTA_OS_MAX,
    AHU_MIN_OA,
    "AHU: Outdoor Air Damper Control Signal",
    "AHU: Heating Coil Valve Control Signal",
    "AHU: Cooling Coil Valve Control Signal",
    "AHU: Supply Air Fan Speed Control Signal"
)


_fc4_report = FaultCodeFourReport(DELTA_OS_MAX)

df = pd.read_csv(args.input, index_col="Date", parse_dates=True)

start = df.head(1).index.date
print("Dataset start: ", start)

end = df.tail(1).index.date
print("Dataset end: ", end)

for col in df.columns:
    print("df column: ", col, "- max: ", df[col].max(), "- col type: ", df[col].dtypes)

print(df.describe())

df["AHU: Heating Coil Valve Control Signal"] = df["AHU: Heating Coil Valve Control Signal"].astype(
    float)

# return a whole new dataframe with fault flag as new col
# data is resampled for hourly averages in df2
df2 = _fc4.apply(df)
print(df2.head())
print(df2.describe())

document = _fc4_report.create_report(args.output, df2)
path = os.path.join(os.path.curdir, "final_report")
if not os.path.exists(path):
    os.makedirs(path)
document.save(os.path.join(path, f"{args.output}.docx"))
