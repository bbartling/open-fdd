import pandas as pd
import pickle
import numpy as np

def test_true_prediction():
    # Load the model
    with open('best_model.pkl', 'rb') as f:
        model = pickle.load(f)

    # Create a pandas DataFrame with a single row of data
    data = {
        'Date': ['8/28/2007 0:00'],
        'AHU: Supply Air Temperature': [75.92],
        'AHU: Supply Air Temperature Set Point': [55],
        'AHU: Outdoor Air Temperature': [80.61],
        'AHU: Mixed Air Temperature': [73.54],
        'AHU: Return Air Temperature': [73.86],
        'AHU: Supply Air Fan Status': [0],
        'AHU: Return Air Fan Status': [0],
        'AHU: Supply Air Fan Speed Control Signal': [0.2],
        'AHU: Return Air Fan Speed Control Signal': [0.2],
        'AHU: Exhaust Air Damper Control Signal': [0],
        'AHU: Outdoor Air Damper Control Signal': [0],
        'AHU: Return Air Damper Control Signal': [1],
        'AHU: Cooling Coil Valve Control Signal': [0],
        'AHU: Heating Coil Valve Control Signal': [0],
        'AHU: Supply Air Duct Static Pressure Set Point': [1.4],
        'AHU: Supply Air Duct Static Pressure': [0],
        'Occupancy Mode Indicator': [0],
    }
    new_data = pd.DataFrame(data)

    # Use the model to make predictions
    faults = model.predict(new_data)

    # Check if the prediction is True (1)
    assert faults[0] == 1

def test_false_prediction():
    # Load the model
    with open('best_model.pkl', 'rb') as f:
        model = pickle.load(f)

    # Create a pandas DataFrame with a single row of data
    data = {
        'Date': ['8/28/2007 0:00'],
        'AHU: Supply Air Temperature': [75.92],
        'AHU: Supply Air Temperature Set Point': [55],
        'AHU: Outdoor Air Temperature': [80.61],
        'AHU: Mixed Air Temperature': [73.54],
        'AHU: Return Air Temperature': [73.86],
        'AHU: Supply Air Fan Status': [0],
        'AHU: Return Air Fan Status': [0],
        'AHU: Supply Air Fan Speed Control Signal': [0.2],
        'AHU: Return Air Fan Speed Control Signal': [0.2],
        'AHU: Exhaust Air Damper Control Signal': [0],
        'AHU: Outdoor Air Damper Control Signal': [0],
        'AHU: Return Air Damper Control Signal': [0],
        'AHU: Cooling Coil Valve Control Signal': [0],
        'AHU: Heating Coil Valve Control Signal': [0],
        'AHU: Supply Air Duct Static Pressure Set Point': [1.4],
        'AHU: Supply Air Duct Static Pressure': [0],
        'Occupancy Mode Indicator': [0],
    }
    new_data = pd.DataFrame(data)

    # Use the model to make predictions
    faults = model.predict(new_data)

    # Check if the prediction is False (0)
    assert faults[0] == 0
