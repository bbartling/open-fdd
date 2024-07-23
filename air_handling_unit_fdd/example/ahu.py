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
