import time
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, AdaBoostRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from datetime import datetime
import matplotlib.pyplot as plt
import joblib

# Load your data
data_path = r"C:\Users\bbartling\Documents\WPCRC_Master.csv"
df = pd.read_csv(data_path)

# Convert the timestamp column to datetime and set it as the index
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

# Print the DataFrame and its columns to verify
print(df)
print(df.columns)

# Remove rows where both CWS_Temp and CWR_Temp are zero
df = df[~((df['CWS_Temp'] == 0) & (df['CWR_Temp'] == 0))]

# Create the chiller delta temperature column
df['chiller_delta_temp'] = df['CWR_Temp'] - df['CWS_Temp']

# Describe the CWS_Temp, CWR_Temp, and chiller_delta_temp
print(df['CWS_Temp'].describe())
print(df['CWR_Temp'].describe())
print(df['chiller_delta_temp'].describe())

# Plotting the descriptions
fig, axes = plt.subplots(2, 1, figsize=(15, 10))

df['CWS_Temp'].plot(ax=axes[0], kind='line', color='blue', label='CWS_Temp', title='CWS_Temp and CWR_Temp')
df['CWR_Temp'].plot(ax=axes[0], kind='line', color='red', label='CWR_Temp')
axes[0].legend()

df['chiller_delta_temp'].plot(ax=axes[1], kind='line', color='green', title='Chiller Delta Temp')

plt.tight_layout()
plt.savefig('chiller_temperature_descriptions.png')
plt.show()

# Drop the chiller temperature columns since they are now part of the target variable
df = df.drop(columns=['CWR_Temp', 'CWS_Temp'])

# Drop rows with missing values
df = df.dropna()

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
def evaluate_lags(df, target_col, max_lag):
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
        rf_model, rf_rmse = train_model(train_df, test_df, target_col, RandomForestRegressor(n_estimators=100, random_state=42))
        ab_model, ab_rmse = train_model(train_df, test_df, target_col, AdaBoostRegressor(n_estimators=100, random_state=42))
        
        avg_rmse = np.mean([rf_rmse, ab_rmse])
        results.append((lag, rf_rmse, ab_rmse, avg_rmse))
        
        if avg_rmse < best_rmse:
            best_rmse = avg_rmse
            best_lag = lag
    
    return best_lag, results

# Model training with RMSE calculation
def train_model(train_data, test_data, target_col, model):
    # Timer start
    start_time = time.time()
    
    # Features and target
    X_train = train_data.drop(columns=[target_col])
    y_train = train_data[target_col]
    
    X_test = test_data.drop(columns=[target_col])
    y_test = test_data[target_col]
    
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))
    print(f"Prediction Model RMSE for {target_col} with {type(model).__name__}: {rmse:.2f}")
    
    # Timer end
    end_time = time.time()
    training_time = (end_time - start_time) / 60  # Convert to minutes
    print(f"Training time for {target_col} with {type(model).__name__}: {training_time:.2f} minutes")
    
    return model, rmse

# Evaluate different lags
max_lag = 5  # Define the maximum lag to test
best_lag, lag_results = evaluate_lags(df, 'chiller_delta_temp', max_lag)
print(f'Best lag: {best_lag}')

# Use the best lag to create lagged features and train models
df = create_lagged_features(df, lag=best_lag)

# Train-test split
train_size = int(0.8 * len(df))
train_df = df[:train_size]
test_df = df[train_size:]

# Initial data collection and model training with both RandomForest and AdaBoost
rf_model, rf_rmse = train_model(train_df, test_df, 'chiller_delta_temp', RandomForestRegressor(n_estimators=100, random_state=42))
ab_model, ab_rmse = train_model(train_df, test_df, 'chiller_delta_temp', AdaBoostRegressor(n_estimators=100, random_state=42))

# Save the best model to file
best_model = rf_model if rf_rmse < ab_rmse else ab_model
joblib.dump(best_model, 'best_chiller_delta_temp_model.pkl')

# Simulated real-time operation
def real_time_prediction(data, models, target_col):
    # Simulate new real-time data (replace this with actual new data in a real scenario)
    new_data = data.sample(n=10)
    
    # Predict the target variable
    features = new_data.drop(columns=[target_col])
    for model in models:
        new_data[f'{target_col}_predicted_{type(model).__name__}'] = model.predict(features)
    
    return new_data

# Real-time operation (simulated for this example)
for _ in range(10):  # Simulate real-time operation
    test_df = real_time_prediction(test_df, [rf_model, ab_model], 'chiller_delta_temp')
    print(test_df[['chiller_delta_temp', 'chiller_delta_temp_predicted_RandomForestRegressor', 'chiller_delta_temp_predicted_AdaBoostRegressor']].tail(1))
