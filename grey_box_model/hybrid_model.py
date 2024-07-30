import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from datetime import datetime, timedelta

# Function to simulate data collection at 5-minute intervals
def collect_data(interval=5):
    now = datetime.now()
    data = {
        'timestamp': [now - timedelta(minutes=interval*i) for i in range(50)],
        'zone_air_temp': np.random.normal(21, 0.5, 50),
        'zone_air_temp_setpoint': np.random.normal(21, 0.5, 50),
        'outside_air_temp': np.random.normal(15, 0.5, 50),
        'occupied_building': np.random.randint(0, 2, 50),
        'building_power': np.random.normal(5, 0.5, 50),
        'chiller_inlet_temp': np.random.normal(12, 0.5, 50),
        'chiller_outlet_temp': np.random.normal(7, 0.5, 50),
        'boiler_inlet_temp': np.random.normal(60, 1, 50),
        'boiler_outlet_temp': np.random.normal(70, 1, 50),
        'ahu_fan_speed': np.random.uniform(0, 1, 50),
        'ahu_damper_command': np.random.uniform(0, 1, 50),
        'ahu_heating_valve': np.random.uniform(0, 1, 50),
        'ahu_cooling_valve': np.random.uniform(0, 1, 50),
        'ahu_duct_static_pressure': np.random.uniform(0, 2, 50),
        'ahu_discharge_air_temp': np.random.normal(14, 0.5, 50),
    }
    
    for i in range(1, 21):
        data[f'vav_{i}_cfm'] = np.random.uniform(0, 1000, 50)
        data[f'vav_{i}_temp_deviation'] = data['zone_air_temp'] - data['zone_air_temp_setpoint']
    
    return pd.DataFrame(data).sort_values(by='timestamp').reset_index(drop=True)

# Data-driven model training with RMSE calculation
def train_models(data):
    X_power = data[['zone_air_temp', 'outside_air_temp', 'occupied_building']]
    y_power = data['building_power']
    model_power = RandomForestRegressor(n_estimators=100, random_state=42)
    model_power.fit(X_power, y_power)
    power_predictions = model_power.predict(X_power)
    power_rmse = np.sqrt(mean_squared_error(y_power, power_predictions))
    print(f"Power Prediction Model RMSE: {power_rmse:.2f}")
    
    X_temp = data[['zone_air_temp', 'outside_air_temp', 'occupied_building', 'building_power']]
    y_temp = data['zone_air_temp'].shift(-1).ffill()
    model_temp = RandomForestRegressor(n_estimators=100, random_state=42)
    model_temp.fit(X_temp, y_temp)
    temp_predictions = model_temp.predict(X_temp)
    temp_rmse = np.sqrt(mean_squared_error(y_temp, temp_predictions))
    print(f"Temperature Prediction Model RMSE: {temp_rmse:.2f}")
    
    return model_power, model_temp

# Real-time prediction and fault detection
def predict_and_detect_faults(data, model_power, model_temp, threshold_temp):
    data['building_power_predicted'] = model_power.predict(data[['zone_air_temp', 'outside_air_temp', 'occupied_building']])
    data['zone_air_temp_predicted'] = model_temp.predict(data[['zone_air_temp', 'outside_air_temp', 'occupied_building', 'building_power']])
    
    data['error_temp'] = np.abs(data['zone_air_temp_predicted'] - data['zone_air_temp'].shift(-1).ffill())
    
    data['fault'] = data['error_temp'] > threshold_temp
    
    return data

# Control and fault management
def adaptive_control_and_fault_management(data, model_power, model_temp, threshold_temp):
    # Collect real-time data
    new_data = collect_data()
    data = pd.concat([new_data, data]).drop_duplicates().reset_index(drop=True)
    
    # Predict and detect faults
    data = predict_and_detect_faults(data, model_power, model_temp, threshold_temp)
    
    # Adaptive control logic (simplified)
    if data['fault'].iloc[-1]:
        print("Fault detected! Investigate the HVAC system.")
    else:
        print("System operating normally.")
    
    return data

# Initial data collection and model training
data = collect_data()
model_power, model_temp = train_models(data)

# Initial threshold
threshold_temp = 1.0

# Real-time operation
for _ in range(10):  # Simulate real-time operation
    data = adaptive_control_and_fault_management(data, model_power, model_temp, threshold_temp)
    print(data[['timestamp', 'zone_air_temp', 'zone_air_temp_predicted', 'building_power', 'building_power_predicted', 'fault']].tail(1))

# Additional model for each VAV zone air temperature deviation
def train_vav_models(data):
    vav_models = {}
    for i in range(1, 21):
        X_vav = data[[f'vav_{i}_cfm', f'vav_{i}_temp_deviation']]
        y_vav = data['zone_air_temp']
        model_vav = RandomForestRegressor(n_estimators=100, random_state=42)
        model_vav.fit(X_vav, y_vav)
        vav_predictions = model_vav.predict(X_vav)
        vav_rmse = np.sqrt(mean_squared_error(y_vav, vav_predictions))
        print(f"VAV {i} Temperature Deviation Model RMSE: {vav_rmse:.2f}")
        vav_models[f'vav_{i}'] = model_vav
    return vav_models

# Train models for each VAV zone
vav_models = train_vav_models(data)

# Real-time VAV zone temperature deviation prediction and fault detection
def predict_and_detect_vav_faults(data, vav_models, threshold_temp):
    for i in range(1, 21):
        data[f'vav_{i}_temp_predicted'] = vav_models[f'vav_{i}'].predict(data[[f'vav_{i}_cfm', f'vav_{i}_temp_deviation']])
        data[f'vav_{i}_error_temp'] = np.abs(data[f'vav_{i}_temp_predicted'] - data['zone_air_temp'].shift(-1).ffill())
        data[f'vav_{i}_fault'] = data[f'vav_{i}_error_temp'] > threshold_temp
    return data

# Real-time operation with VAV fault detection
for _ in range(10):  # Simulate real-time operation
    data = adaptive_control_and_fault_management(data, model_power, model_temp, threshold_temp)
    data = predict_and_detect_vav_faults(data, vav_models, threshold_temp)
    print(data[['timestamp', 'zone_air_temp', 'zone_air_temp_predicted', 'building_power', 'building_power_predicted', 'fault']].tail(1))
