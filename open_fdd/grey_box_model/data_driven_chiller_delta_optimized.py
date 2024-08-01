import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
import joblib
import matplotlib.pyplot as plt


def create_lagged_features(df, lag):
    """Create lagged features for a DataFrame."""
    lagged_df = pd.concat([df.shift(i) for i in range(1, lag + 1)], axis=1)
    new_cols = [f'{col}_lag{i}' for i in range(1, lag + 1) for col in df.columns]
    lagged_df.columns = new_cols
    return pd.concat([df, lagged_df], axis=1).dropna()

def make_plots(df):
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
    #plt.show()

def load_and_prepare_data(filepath):
    """Load, clean, and preprocess the data."""
    df = pd.read_csv(filepath, parse_dates=['timestamp'], index_col='timestamp')
    df = df[(df['CWS_Temp'] != 0) & (df['CWR_Temp'] != 0)]
    df['chiller_delta_temp'] = df['CWR_Temp'] - df['CWS_Temp']
    make_plots(df)
    df.drop(columns=['CWR_Temp', 'CWS_Temp'], inplace=True)
    return df.dropna()

def evaluate_lags(df, max_lag):
    """Evaluate different lags to find the best based on RMSE."""
    best_rmse = np.inf
    best_lag = None
    for lag in range(1, max_lag + 1):
        temp_df = create_lagged_features(df[['chiller_delta_temp']], lag)
        train_df, test_df = train_test_split(temp_df, test_size=0.2, random_state=42)
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(train_df.drop('chiller_delta_temp', axis=1), train_df['chiller_delta_temp'])
        predictions = model.predict(test_df.drop('chiller_delta_temp', axis=1))
        rmse = np.sqrt(mean_squared_error(test_df['chiller_delta_temp'], predictions))
        print(f"Lag: {lag}, RMSE: {rmse}")
        if rmse < best_rmse:
            best_rmse = rmse
            best_lag = lag
    return best_lag

df = load_and_prepare_data("C:/Users/bbartling/Documents/WPCRC_Master.csv")
best_lag = evaluate_lags(df, 5)
print(f"The best lag found is: {best_lag}")

# Prepare data with the best lag
df = create_lagged_features(df[['chiller_delta_temp']], best_lag)
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

# Train and save the model
model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(train_df.drop('chiller_delta_temp', axis=1), train_df['chiller_delta_temp'])
joblib.dump(model, 'best_chiller_delta_temp_model.pkl')
