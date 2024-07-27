# open-fdd

This is a Python based FDD tool for running fault equations inspired by ASHRAE Guideline 36 for HVAC systems across historical datasets with the Pandas computing library. Word documents are generated programmatically with the Python Docx library.

* See `README` inside the `air_handling_unit` directory for further instructions.

## UNDER ACTIVE DEVELOPMENT - 7/23/24
* Some features may be broken or not work as expected while the project is undergoing a significant makeover to become installable from PyPI. The aim is to streamline the reporting processes and make them much easier to use. We appreciate your patience during this transition.

**GOALS** 
1. Update AHU fault rules to be a Combined condition check, see Git Issue
2. Update unit tests for Combined condition check
3. Publish as a Python library to PyPI
4. Ultimate goal is to be able to make reports like this below with `pip` and `pandas`

```python
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
report.create_report(current_dir, df_faults, report_name="ahu1_fc1.docx")
```

## Word Doc Reporting
![Alt text](air_handling_unit/images/ahu1_fc1-1.jpg)
![Alt text](/air_handling_unit/images/ahu1_fc1-2.jpg)

## Contribute
This project is a community-driven initiative, focusing on the development of free and open-source tools. I believe that Fault Detection and Diagnostics (FDD) should be free and accessible to anyone who wants to try it out, embodying the spirit of open-source philosophy. I think I have heard some wise person say something along the lines...

>"You can't patent fricken physics..."

This quote captures my ethos. In the world of rapid technological advancement, I stand for open and accessible innovation. I encourage contributions from all who share this vision. Whether it's by contributing code, documentation, ideas, or feedback, your involvement is valued and essential for the growth of this project.


## License

【MIT License】

Copyright 2024 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
