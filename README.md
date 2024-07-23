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
from open_fdd.air_handling_unit.faults import FaultConditionOne
from open_fdd.air_handling_unit.reports import FaultCodeOneReport
from open_fdd.config import default_config

# Load your data
df = pd.read_csv("path_to_your_data.csv")

# Load the configuration
config = default_config.config_dict

# Apply fault conditions
fc1 = FaultConditionOne(config)
df_faults = fc1.apply(df)

# Generate reports
report = FaultCodeOneReport(config)
document = report.create_report("path_to_save_report", df_faults)
document.save("path_to_save_report/report_fc1.docx")
```


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
