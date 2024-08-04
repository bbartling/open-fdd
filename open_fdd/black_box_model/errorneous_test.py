import pandas as pd
import numpy as np
import joblib

def create_lagged_features(df, lag, column_name):
    """Create lagged features for a DataFrame."""
    series = df[column_name]
    lagged_df = pd.concat([series.shift(i) for i in range(1, lag + 1)], axis=1)
    new_cols = [f'{column_name}_lag{i}' for i in range(1, lag + 1)]
    lagged_df.columns = new_cols
    return lagged_df

# Load the saved model
model_path = 'best_chiller_delta_temp_model.pkl'
model = joblib.load(model_path)

# Create a pandas DataFrame with fake data (adjusted to only have the needed column)
fake_data = {
    'chiller_delta_temp': [9.400, 9.420, 9.380, 9.410, 9.390, 9.370, 9.360, 9.350, 9.340, 9.330]
}

fake_df = pd.DataFrame(fake_data)

# Define the lag
lag = 5

# Create lagged features based on the 'chiller_delta_temp' column
fake_df_lagged = create_lagged_features(fake_df, lag, 'chiller_delta_temp')
fake_df_lagged = fake_df_lagged.dropna()  # Ensure no NaN rows if any

if not fake_df_lagged.empty:
    # Predict using the model if there are enough rows
    predictions = model.predict(fake_df_lagged)
    print("Predictions on fake data:", predictions)
else:
    print("Not enough data to apply lagging correctly. Need more than", lag, "rows.")
