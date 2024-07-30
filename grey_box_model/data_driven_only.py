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

# Train-test split
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

# Data-driven model training with RMSE calculation
def train_models(train_data, test_data):
    # Target Variable for Building Power Meter
    X_train_power = train_data.drop(columns=[additional_columns['BUILDING_POWER_METER']])
    y_train_power = train_data[additional_columns['BUILDING_POWER_METER']]
    
    X_test_power = test_data.drop(columns=[additional_columns['BUILDING_POWER_METER']])
    y_test_power = test_data[additional_columns['BUILDING_POWER_METER']]
    
    model_power = RandomForestRegressor(n_estimators=100, random_state=42)
    model_power.fit(X_train_power, y_train_power)
    power_predictions = model_power.predict(X_test_power)
    power_rmse = np.sqrt(mean_squared_error(y_test_power, power_predictions))
    print(f"Building Power Meter Prediction Model RMSE: {power_rmse:.2f}")
    
    # Target Variable for Return Air Temperature
    X_train_temp = train_data.drop(columns=[ahu_columns['RAT_COL']])
    y_train_temp = train_data[ahu_columns['RAT_COL']].shift(-1).ffill()
    
    X_test_temp = test_data.drop(columns=[ahu_columns['RAT_COL']])
    y_test_temp = test_data[ahu_columns['RAT_COL']].shift(-1).ffill()
    
    model_temp = RandomForestRegressor(n_estimators=100, random_state=42)
    model_temp.fit(X_train_temp, y_train_temp)
    temp_predictions = model_temp.predict(X_test_temp)
    temp_rmse = np.sqrt(mean_squared_error(y_test_temp, temp_predictions))
    print(f"Return Air Temperature Prediction Model RMSE: {temp_rmse:.2f}")
    
    return model_power, model_temp

# Real-time prediction and fault detection
def predict_and_detect_faults(data, model_power, model_temp, threshold_temp):
    # Exclude 'Building_Power_Meter_predicted' from features
    features = data.drop(columns=[additional_columns['BUILDING_POWER_METER'], 'Building_Power_Meter_predicted', ahu_columns['RAT_COL']])
    
    # Predicted Variable for Building Power Meter
    data['Building_Power_Meter_predicted'] = model_power.predict(features)
    
    # Exclude 'RaTemp_predicted' from features
    features = data.drop(columns=[additional_columns['BUILDING_POWER_METER'], 'Building_Power_Meter_predicted', 'RaTemp_predicted'])
    
    # Predicted Variable for Return Air Temperature
    data['RaTemp_predicted'] = model_temp.predict(features)
    
    # Calculate error and detect faults
    data['error_temp'] = np.abs(data['RaTemp_predicted'] - data[ahu_columns['RAT_COL']].shift(-1).ffill())
    data['fault'] = data['error_temp'] > threshold_temp
    
    return data

# Control and fault management
def adaptive_control_and_fault_management(data, model_power, model_temp, threshold_temp):
    # Simulate new real-time data (replace this with actual new data in a real scenario)
    new_data = data.sample(n=10)
    
    # Predict and detect faults
    data = pd.concat([new_data, data]).drop_duplicates().reset_index(drop=True)
    data = predict_and_detect_faults(data, model_power, model_temp, threshold_temp)
    
    # Adaptive control logic (simplified)
    if data['fault'].iloc[-1]:
        print("Fault detected! Investigate the HVAC system.")
    else:
        print("System operating normally.")
    
    return data

# Initial data collection and model training
model_power, model_temp = train_models(train_df, test_df)

# Initial threshold
threshold_temp = 1.0

# Simulated Real-time operation
for _ in range(10):  # Simulate real-time operation
    test_df = adaptive_control_and_fault_management(test_df, model_power, model_temp, threshold_temp)
    print(test_df[[ahu_columns['OAT_COL'], ahu_columns['RAT_COL'], 'RaTemp_predicted', additional_columns['BUILDING_POWER_METER'], 'Building_Power_Meter_predicted', 'fault']].tail(1))

# Additional model for each VAV zone air temperature deviation
def train_vav_models(train_data, test_data):
    vav_models = {}
    for vav_col in vav_columns:
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
    return vav_models

# Train models for each VAV zone
vav_models = train_vav_models(train_df, test_df)

# Real-time VAV zone temperature deviation prediction and fault detection
def predict_and_detect_vav_faults(data, vav_models, threshold_temp):
    for vav_col in vav_columns:
        # Exclude the target column and predicted columns from the features
        features = data.drop(columns=[vav_col, 'Building_Power_Meter_predicted', 'RaTemp_predicted'])
        
        # Predicted Variable for VAV Space Temperature
        data[f'{vav_col}_temp_predicted'] = vav_models[vav_col].predict(features)
        data[f'{vav_col}_error_temp'] = np.abs(data[f'{vav_col}_temp_predicted'] - data[vav_col].shift(-1).ffill())
        data[f'{vav_col}_fault'] = data[f'{vav_col}_error_temp'] > threshold_temp
    return data

# Real-time operation with VAV fault detection (simulated for this example)
for _ in range(10):  # Simulate real-time operation
    test_df = adaptive_control_and_fault_management(test_df, model_power, model_temp, threshold_temp)
    test_df = predict_and_detect_vav_faults(test_df, vav_models, threshold_temp)
    print(test_df[[ahu_columns['OAT_COL'], ahu_columns['RAT_COL'], 'RaTemp_predicted', additional_columns['BUILDING_POWER_METER'], 'Building_Power_Meter_predicted', 'fault']].tail(1))
