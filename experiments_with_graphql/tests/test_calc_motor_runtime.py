import pandas as pd

# Load the data
df = pd.read_csv("./ahu_data.csv", parse_dates=["Date"])

# Ensure 'Date' is the index and is a DateTimeIndex
df.set_index('Date', inplace=True)

# Filter to get the times when the motor is running
running_times = df[df['SF Spd%'] > 5.0].copy()

# Calculate time differences between consecutive timestamps
running_times['time_diff'] = running_times.index.to_series().diff()

# Convert time differences to hours
running_times['time_diff_hours'] = running_times['time_diff'].dt.total_seconds() / 3600

# Sum up these time differences for each day
daily_motor_runtime = running_times['time_diff_hours'].resample('D').sum()

# Reset the index to turn the dates back into a column
daily_motor_runtime = daily_motor_runtime.reset_index()

# Rename columns for clarity
daily_motor_runtime.columns = ['day', 'total_runtime_hours']

# Print daily total runtime
print(daily_motor_runtime)
