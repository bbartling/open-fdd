import time
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from datetime import datetime

# Load your data
data_path = r"C:\Users\bbartling\Documents\WPCRC_Master.csv"
df = pd.read_csv(data_path)

# Convert the timestamp column to datetime and set it as the index
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

# Print the DataFrame and its columns to verify
print(df)
print(df.columns)

# Define the relevant columns for the AHU
ahu_columns = {
    'DUCT_STATIC_COL': "SaStatic",
    'DUCT_STATIC_SETPOINT_COL': "SaStaticSPt",
    'SUPPLY_VFD_SPEED_COL': "Sa_FanSpeed",
    'MAT_COL': "MA_Temp",
    'OAT_COL': "OaTemp",
    'SAT_COL': "SaTempSP",
    'RAT_COL': "RaTemp",
    'HEATING_SIG_COL': "HW_Valve",  
    'COOLING_SIG_COL': "CW_Valve",  
    'ECONOMIZER_SIG_COL': "OA_Damper"
}

# Define the relevant columns for the additional data
additional_columns = {
    'BUILDING_POWER_METER': "CurrentKW",
    'BOILER_INLET_TEMP': "HWR_value",
    'BOILER_OUTLET_TEMP': "HWS_value",
    'CHILLER_INLET_TEMP': "CWR_Temp",
    'CHILLER_OUTLET_TEMP': "CWS_Temp"
}

# Define VAV box space temperature columns
vav_columns = [
    'VAV2_6_SpaceTemp', 'VAV2_7_SpaceTemp', 'VAV3_2_SpaceTemp', 'VAV3_5_SpaceTemp'
]

# Drop rows with missing values
df = df[list(ahu_columns.values()) + list(additional_columns.values()) + vav_columns].dropna()

# Create lagged features for each column
def create_lagged_features(df, lag=1):
    for col in df.columns:
        for l in range(1, lag + 1):
            df[f'{col}_lag{l}'] = df[col].shift(l)
    return df.dropna()

# Add time-based features to capture seasonality
df['hour'] = df.index.hour
df['day_of_week'] = df.index.dayofweek
df['month'] = df.index.month

# Function to evaluate different lags
def evaluate_lags(df, max_lag):
    best_lag = 0
    best_rmse = float('inf')
    results = []
    
    for lag in range(1, max_lag + 1):
        lagged_df = create_lagged_features(df.copy(), lag)
        
        # Train-test split
        train_size = int(0.8 * len(lagged_df))
        train_df = lagged_df[:train_size]
        test_df = lagged_df[train_size:]
        
        # Train models and calculate RMSE
        vav_models, vav_rmse_results = train_vav_models(train_df, test_df)
        
        avg_rmse = np.mean([result[1] for result in vav_rmse_results])
        results.append((lag, avg_rmse))
        
        if avg_rmse < best_rmse:
            best_rmse = avg_rmse
            best_lag = lag
    
    return best_lag, results

# Additional model for each VAV zone air temperature deviation
def train_vav_models(train_data, test_data):
    vav_models = {}
    vav_rmse_results = []
    for vav_col in vav_columns:
        # Timer start
        start_time = time.time()
        
        # Drop the target column from the features
        X_train_vav = train_data.drop(columns=[vav_col])
        y_train_vav = train_data[vav_col]
        
        X_test_vav = test_data.drop(columns=[vav_col])
        y_test_vav = test_data[vav_col]
        
        model_vav = RandomForestRegressor(n_estimators=100, random_state=42)
        model_vav.fit(X_train_vav, y_train_vav)
        vav_predictions = model_vav.predict(X_test_vav)
        vav_rmse = np.sqrt(mean_squared_error(y_test_vav, vav_predictions))
        print(f"{vav_col} Space Temperature Model RMSE: {vav_rmse:.2f}")
        vav_models[vav_col] = model_vav
        
        # Timer end
        end_time = time.time()
        training_time = (end_time - start_time) / 60  # Convert to minutes
        print(f"Training time for {vav_col}: {training_time:.2f} minutes")
        
        vav_rmse_results.append((vav_col, vav_rmse))
        
    return vav_models, vav_rmse_results

# Evaluate different lags
max_lag = 5  # Define the maximum lag to test
best_lag, lag_results = evaluate_lags(df, max_lag)
print(f'Best lag: {best_lag}')

# Use the best lag to create lagged features and train models
df = create_lagged_features(df, lag=best_lag)

# Train-test split
train_size = int(0.8 * len(df))
train_df = df[:train_size]
test_df = df[train_size:]

# Train models for each VAV zone
vav_models, vav_rmse_results = train_vav_models(train_df, test_df)

# Real-time VAV zone temperature deviation prediction and fault detection
def predict_and_detect_vav_faults(data, vav_models, threshold_temp):
    for vav_col in vav_columns:
        # Exclude the target column and predicted columns from the features
        features = data.drop(columns=[vav_col])
        
        # Predicted Variable for VAV Space Temperature
        data[f'{vav_col}_temp_predicted'] = vav_models[vav_col].predict(features)
        data[f'{vav_col}_error_temp'] = np.abs(data[f'{vav_col}_temp_predicted'] - data[vav_col].shift(-1).ffill())
        data[f'{vav_col}_fault'] = data[f'{vav_col}_error_temp'] > threshold_temp
    return data

# Initial threshold
threshold_temp = 1.0

# Simulated Real-time operation
for _ in range(10):  # Simulate real-time operation
    test_df = predict_and_detect_vav_faults(test_df, vav_models, threshold_temp)
    print(test_df[[ahu_columns['OAT_COL'], ahu_columns['RAT_COL']] + [f'{vav_col}_temp_predicted' for vav_col in vav_columns] + [f'{vav_col}_fault' for vav_col in vav_columns]].tail(1))
