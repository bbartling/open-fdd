import pandas as pd
import matplotlib.pyplot as plt

# Specify the file path for raw data
egauge_35201_file = r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_raw\egauge\35201.csv"
main_meter_file = r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_raw\egauge\Main_year_only.csv"
solar_file = r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_raw\egauge\PV_year_only.csv"
weather_file = r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_raw\weather\3363508_trimmed.csv"

# Read the CSV files into DataFrames
ahu_electricity = pd.read_csv(egauge_35201_file)
main_meter_electricity = pd.read_csv(main_meter_file)
solar_electricity = pd.read_csv(solar_file)
weather = pd.read_csv(weather_file)

# Convert date columns to datetime type and set as index
ahu_electricity["Central"] = pd.to_datetime(ahu_electricity["Central"])
ahu_electricity.set_index("Central", inplace=True)

main_meter_electricity["Central"] = pd.to_datetime(main_meter_electricity["Central"])
main_meter_electricity.set_index("Central", inplace=True)

solar_electricity["Central"] = pd.to_datetime(solar_electricity["Central"])
solar_electricity.set_index("Central", inplace=True)

weather["Date"] = pd.to_datetime(weather["Date"])
weather.set_index("Date", inplace=True)
weather = weather.loc[~weather.index.duplicated(keep='first')]
weather = weather.resample('T').ffill()


# Select desired columns and perform operations
ahu_columns = ["p_mdp_rtu_a", "p_mdp_rtu_b", "p_mdp_rtu_c"]
ahu_electricity = ahu_electricity[ahu_columns]
ahu_electricity["ahu_all_power"] = ahu_electricity.sum(axis=1)

main_columns = ["p_mdp_panel_a", "p_mdp_panel_b", "p_mdp_panel_c"]
main_meter_electricity = main_meter_electricity[main_columns]
main_meter_electricity["main_all_power"] = main_meter_electricity.sum(axis=1)

solar_columns = ["Inverter 1", "Inverter 2", "Inverter 3"]
solar_electricity = solar_electricity[solar_columns]
solar_electricity["solar_all_power"] = solar_electricity.sum(axis=1)

# Trim files down
start_date = "2021-02-27"
end_date = "2022-10-23"
ahu_electricity = ahu_electricity.loc[start_date:end_date]
main_electricity = main_meter_electricity.loc[start_date:end_date]
solar_electricity = solar_electricity.loc[start_date:end_date]
weather = weather.loc[start_date:end_date]

# Initialize combined_data DataFrame
combined_data = pd.DataFrame()

# Combine the two DataFrames using merge
combined_data = pd.merge(
    ahu_electricity, main_meter_electricity, left_index=True, right_index=True
)
combined_data = pd.merge(
    combined_data, solar_electricity, left_index=True, right_index=True
)
combined_data = pd.merge(combined_data, weather, left_index=True, right_index=True)

print(combined_data.columns)
combined_data = combined_data[
    [
        "main_all_power",
        "ahu_all_power",
        "HourlyDewPointTemperature",
        "HourlyDryBulbTemperature",
        "HourlyRelativeHumidity",
        "solar_all_power",
    ]
]
combined_data = combined_data.resample('15T').mean()
combined_data.to_csv(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\combined_power_weather\combined_data.csv")

solar_electricity = solar_electricity.resample('15T').mean()
solar_electricity.to_csv(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\solar_electricity.csv")

main_meter_electricity = main_meter_electricity.resample('15T').mean()
main_meter_electricity.to_csv(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\main_meter_electricity.csv")

ahu_electricity = ahu_electricity.resample('15T').mean()
ahu_electricity.to_csv(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\ahu_electricity.csv")

weather = weather.resample('15T').mean()
weather.to_csv(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\weather\weather.csv")

# Create subplots and plot the data
combined_data.plot(subplots=True, figsize=(10, 12))
print(combined_data.head())

# Adjust the layout
plt.tight_layout()

# Save the plot to a file
plt.savefig(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\combined_power_weather\combined_data_subplots.png")

# Display the plot
plt.show()

combined_data.reset_index().to_feather(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\combined_power_weather\combined_data.feather")
solar_electricity.reset_index().to_feather(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\solar_electricity.feather")
main_meter_electricity.reset_index().to_feather(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\main_meter_electricity.feather")
ahu_electricity.reset_index().to_feather(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\egauge\ahu_electricity.feather")
weather.reset_index().to_feather(r"C:\Users\bbartling\Slipstream\Solution Foundry - Analysis\data_processed\weather\weather.feather")
