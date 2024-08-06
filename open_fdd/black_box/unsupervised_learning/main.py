import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os

# Switch backend to non-interactive mode
import matplotlib
matplotlib.use('Agg')  # Use a non-interactive backend like Agg

# Load data
data = pd.read_csv(r"C:\Users\bbartling\Documents\WPCRC_Master.csv")

# Convert timestamp to datetime
data['timestamp'] = pd.to_datetime(data['timestamp'])

# Select all relevant features for analysis (you can add more features as needed)
features = data.columns.drop(['timestamp'])

# Filter and preprocess data
data_filtered = data[features].fillna(data[features].median())
scaler = StandardScaler()
data_normalized = scaler.fit_transform(data_filtered)

# Train Isolation Forest
model = IsolationForest(n_estimators=100, contamination=0.01, random_state=42)
model.fit(data_normalized)

# Predict anomalies
data['anomaly'] = model.predict(data_normalized)
data['anomaly'] = data['anomaly'].map({1: 0, -1: 1})  # Convert -1 (outlier) to 1 for easier interpretation

# Calculate the delta temperature for the chiller
data['chiller_delta_temp'] = data['CWR_Temp'] - data['CWS_Temp']

# Filter data for when the chiller is running (Sa_FanSpeed > 20.0)
running_data = data[data['Sa_FanSpeed'] > 20.0]

# Separate data by anomaly status
anomaly_data = running_data[running_data['anomaly'] == 1]
normal_data = running_data[running_data['anomaly'] == 0]

# Columns to analyze
columns_to_analyze = ['CurrentKW', 'CoolValve', 'DischargeTemp', 'VAV2_6_SpaceTemp', 'RaHumidity', 'RA_Temp']

# Calculate statistics for anomaly data
anomaly_stats = anomaly_data[columns_to_analyze].describe().T
anomaly_stats['anomaly_status'] = 'Anomaly'

# Calculate statistics for normal data
normal_stats = normal_data[columns_to_analyze].describe().T
normal_stats['anomaly_status'] = 'Normal'

# Combine statistics
combined_stats = pd.concat([anomaly_stats, normal_stats], axis=0)

# Save statistics to CSV
combined_stats.to_csv('anomaly_vs_normal_statistics.csv')

# Save timestamps of anomalies to CSV
anomaly_timestamps = anomaly_data[['timestamp', 'chiller_delta_temp']]
anomaly_timestamps.to_csv('anomaly_timestamps.csv', index=False)

# Display statistics
print(combined_stats)

# Plot statistics
fig, axes = plt.subplots(len(columns_to_analyze), 1, figsize=(10, 20))
for i, column in enumerate(columns_to_analyze):
    axes[i].boxplot([normal_data[column], anomaly_data[column]], tick_labels=['Normal', 'Anomaly'])
    axes[i].set_title(f'{column} by Anomaly Status')
    axes[i].set_ylabel(column)

plt.tight_layout()
plt.savefig('anomaly_vs_normal_boxplots.png')

# Plotting chiller_delta_temp over time with anomalies
fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(data['timestamp'], data['chiller_delta_temp'], label='Chiller Delta Temp')
ax.plot(anomaly_data['timestamp'], anomaly_data['chiller_delta_temp'], 'ro', markersize=5, label='Anomaly')
ax.set_title('Chiller Delta Temperature (CWR_Temp - CWS_Temp) Over Time')
ax.set_xlabel('Time')
ax.set_ylabel('Chiller Delta Temperature')
ax.legend()
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
plt.savefig('chiller_delta_temp_anomalies_timeseries.png')

# Extract unique anomaly dates
anomaly_dates = anomaly_data['timestamp'].dt.date.unique()

# Create a directory for saving the plots
output_dir = 'anomaly_plots'
os.makedirs(output_dir, exist_ok=True)

# Create combined line plots for each anomaly date
for anomaly_date in anomaly_dates:
    day_before = pd.Timestamp(anomaly_date) - pd.Timedelta(days=1)
    day_after = pd.Timestamp(anomaly_date) + pd.Timedelta(days=1)
    
    combined_data = data[(data['timestamp'].dt.date >= day_before.date()) & (data['timestamp'].dt.date <= day_after.date())]
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    for column in columns_to_analyze:
        ax.plot(combined_data['timestamp'], combined_data[column], label=f'{column}')

    # Highlight anomaly points
    anomaly_points = combined_data[combined_data['anomaly'] == 1]
    if not anomaly_points.empty:
        ax.plot(anomaly_points['timestamp'], anomaly_points[column], 'ro', markersize=5, label='Anomaly')

    ax.set_title(f'Metrics Around Anomaly Date {anomaly_date}')
    ax.set_xlabel('Time')
    ax.set_ylabel('Value')
    ax.legend(loc='upper right')
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))  # Set interval of ticks
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))  # Format datetime
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f'all_metrics_around_anomaly_{anomaly_date}.png'))
    plt.close()
