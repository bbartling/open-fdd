import pandas as pd
import numpy as np

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from helpers import *

import argparse

# example usage on Windows python 3.10
# py -3.10  main.py --test_case_id 10A_4 --show_plots True
# py -3.10 main.py --test_case_id 10A_4
# py -3.10 main.py --test_case_id 10A_4 --method closest_weather_dates

ALL_DATA_FILE = "./power_data/processed_power_weather/combined_data.csv"
DATES_FILE = "eventInfo.csv"
REPORTS_DIR = "./final_report/"


# Create the parser
parser = argparse.ArgumentParser(description="Process some parameters.")

# Add the parameters
parser.add_argument("--test_case_id", type=str, required=True, help="Test case id.")
parser.add_argument(
    "--show_plots", type=bool, required=False, default=False, help="Flag to show plots."
)
parser.add_argument(
    "--method",
    type=str,
    required=False,
    default="previous_10_days",
    help="previous_10_days or closest_weather_dates",
)

# Parse the arguments
args = parser.parse_args()

# Set the variables from the arguments
test_case_id = args.test_case_id
show_plots = args.show_plots
method = args.method

if method == "previous_10_days":
    REPORTS_DIR += "/10_previous_days"
elif method == "closest_weather_dates":
    REPORTS_DIR += "/10_closest_weather_days"

all_data = pd.read_csv(ALL_DATA_FILE)
dates = pd.read_csv(DATES_FILE)
print(dates.columns)

suitable_baselines = dates.copy()
suitable_baselines = suitable_baselines[["Suitable Baseline Day?", "Date"]]
suitable_baselines = suitable_baselines[
    suitable_baselines["Suitable Baseline Day?"] == "N"
]
suitable_baseline_no = suitable_baselines.drop(
    "Suitable Baseline Day?", axis=1
).dropna()
print("suitable_baseline_dates:\n", suitable_baseline_no)

# Drop rows with missing 'Date' in 'dates'
dates = dates.dropna(subset=["Date"])

# format time stamp
dates["Date"] = pd.to_datetime(dates["Date"], format="%A, %B %d, %Y", errors="coerce")

# drop a unamed col and format time stamp
all_data = all_data.rename(columns={"Unnamed: 0": "Date"})
all_data["Date"] = pd.to_datetime(all_data["Date"], errors="coerce")
print("all_data:\n", all_data)

# Find the date corresponding to Test Case # test_case_id
test_case_date = dates[dates["Test Case #"] == test_case_id]["Date"].min()
formatted_date = test_case_date.strftime("%m-%d-%Y")
print("test_case_date:\n", formatted_date)

test_case_data = all_data[all_data["Date"].dt.date == test_case_date.date()]
print("test_case_data:\n", test_case_data)  # actual power data from test day

main_max_test_day, main_total_energy_test_day = meters_stats_calcs(  # test day avg data
    test_case_data.copy(), "main_all_power"
)
ahu_max_test_day, ahu_total_energy_test_day = meters_stats_calcs(  # test day avg data
    test_case_data.copy(), "ahu_all_power"
)
(
    solar_max_test_day,
    solar_total_energy_test_day,
) = meters_stats_calcs(  # test day avg data
    test_case_data.copy(), "solar_all_power"
)


# Filter all_data DataFrame based on the chosen method
if method == "previous_10_days":
    print("FILTERING DATA with previous_10_days")
    filtered_data_copy = find_previous_10_days(
        suitable_baseline_no, all_data, test_case_date
    )

elif method == "closest_weather_dates":
    print("FILTERING DATA with closest_weather_dates")
    filtered_data_copy = find_closest_weather_dates(
        all_data, suitable_baseline_no, test_case_date, num_dates=10
    )

print("filtered_data_copy:\n", filtered_data_copy)

filtered_data_plot = plot_data_to_be_avg(filtered_data_copy)

if show_plots:
    plt.show()

# make calcs
main_avg_dict, ahu_avg_dict, solar_avg_dict = calculate_power_averages(
    filtered_data_copy
)

main_all_power_avg_combined_data = pd.DataFrame(main_avg_dict)
ahu_all_power_avg_combined_data = pd.DataFrame(ahu_avg_dict)
solar_all_power_avg_combined_data = pd.DataFrame(solar_avg_dict)


main_max_, main_total_energy_ = meters_stats_calcs(  # 10 day avg data
    main_all_power_avg_combined_data.copy(), "main_power_average"
)
ahu_max_, ahu_total_energy_ = meters_stats_calcs(  # 10 day avg data
    ahu_all_power_avg_combined_data.copy(), "ahu_power_average"
)
solar_max_, solar_total_energy_10_day = meters_stats_calcs(  # 10 day avg data
    solar_all_power_avg_combined_data.copy(), "solar_power_average"
)


(
    main_test_day_plot,
    main_combined_data_copy,
    test_start_hour,
    test_end_hour,
) = generate_power_plot(
    "main",
    main_all_power_avg_combined_data,
    test_case_data,
    dates,
    test_case_id,
)


(
    ahu_test_day_plot,
    ahu_combined_data_copy,
    test_start_hour,
    test_end_hour,
) = generate_power_plot(
    "ahu",
    ahu_all_power_avg_combined_data,
    test_case_data,
    dates,
    test_case_id,
)

if show_plots:
    plt.show()


print("main_combined_data_copy:\n", main_combined_data_copy)

# calc event savings
main_average_net_diff_event, main_average_perc_diff_event = calculate_differences(
    main_combined_data_copy, "main", test_case_id, test_start_hour, test_end_hour
)

ahu_average_net_diff_event, ahu_average_perc_diff_event = calculate_differences(
    ahu_combined_data_copy, "ahu", test_case_id, test_start_hour, test_end_hour
)

# Filter all_data DataFrame based on the chosen method
if method == "previous_10_days":
    title = f"10 Previous Weekdays Avg Summary"

elif method == "closest_weather_dates":
    title = f"10 Closest Weather Days Summary"

print("filtered_data_copy:\n", filtered_data_copy)

document = generate_report(
    test_case_id,
    formatted_date,
    filtered_data_plot,
    test_start_hour,
    test_end_hour,
    main_test_day_plot,
    main_average_net_diff_event,
    main_average_perc_diff_event,
    main_max_,
    main_max_test_day,
    main_total_energy_,
    main_total_energy_test_day,
    ahu_test_day_plot,
    ahu_average_net_diff_event,
    ahu_average_perc_diff_event,
    ahu_max_,
    ahu_max_test_day,
    ahu_total_energy_,
    ahu_total_energy_test_day,
    title,
)

# Save the document to the REPORTS_DIR
document.save(os.path.join(REPORTS_DIR, f"test_case_{test_case_id}_report.docx"))
print(f"REPORT SUCCESS {test_case_id}")
