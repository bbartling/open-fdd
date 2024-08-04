import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error
import joblib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import seaborn as sns

def create_lagged_features(df, lag):
    """Create lagged features for a DataFrame."""
    lagged_df = pd.concat([df.shift(i) for i in range(1, lag + 1)], axis=1)
    new_cols = [f'{col}_lag{i}' for i in range(1, lag + 1) for col in df.columns]
    lagged_df.columns = new_cols
    return pd.concat([df, lagged_df], axis=1).dropna()

def load_and_prepare_new_data(filepath):
    """Load, clean, and preprocess the new data."""
    df = pd.read_csv(filepath, parse_dates=['timestamp'], index_col='timestamp')
    print("Columns in the new dataset:", df.columns)
    required_columns = ['CWS_Temp', 'CWR_Temp', 'OaTemp']
    for col in required_columns:
        if col not in df.columns:
            raise KeyError(f"Required column '{col}' not found in the dataset")
    df = df[(df['CWS_Temp'] != 0) & (df['CWR_Temp'] != 0)]
    df['chiller_delta_temp'] = df['CWR_Temp'] - df['CWS_Temp']
    return df.dropna()

def predict_and_evaluate(model_path, data_path, best_lag):
    """Load model, predict and evaluate on new data."""
    df = load_and_prepare_new_data(data_path)
    df_lagged = create_lagged_features(df[['chiller_delta_temp']], best_lag)

    # Load the model
    model = joblib.load(model_path)

    # Predict
    X = df_lagged.drop('chiller_delta_temp', axis=1)
    y_true = df_lagged['chiller_delta_temp']
    #print(X)
    #X.to_csv("X.csv")
    y_pred = model.predict(X)

    # Reindex predictions to align with the dataframe's index
    y_pred_series = pd.Series(y_pred, index=y_true.index)

    # Calculate RMSE
    rmse = np.sqrt(mean_squared_error(y_true, y_pred_series))
    print(f"RMSE on the new data: {rmse}")

    # Plotting actual vs predicted
    plt.figure(figsize=(15, 5))
    plt.plot(y_true, label='Actual', color='blue')
    plt.plot(y_pred_series, label='Predicted', color='red', alpha=0.7)
    plt.legend()
    plt.title('Actual vs Predicted Chiller Delta Temperature')
    plt.xlabel('Time')
    plt.ylabel('Chiller Delta Temp')
    plt.tight_layout()
    #plt.show()

    # Zooming in on the day with the highest outside air temperature
    max_oa_temp_day = df['OaTemp'].idxmax().normalize()
    max_oa_temp = df.loc[max_oa_temp_day.strftime('%Y-%m-%d'), 'OaTemp'].max()
    df_day = df_lagged.loc[max_oa_temp_day.strftime('%Y-%m-%d')]
    y_true_day = y_true[df_day.index]
    y_pred_day = y_pred_series[df_day.index]

    plt.figure(figsize=(15, 5))
    plt.plot(y_true_day, label='Actual', color='blue')
    plt.plot(y_pred_day, label='Predicted', color='red', alpha=0.7)
    plt.legend()
    plt.title(f'Actual vs Predicted Chiller Delta Temperature on {max_oa_temp_day.date()}')
    plt.xlabel('Time')
    plt.ylabel('Chiller Delta Temp')

    # Format X-axis to show hours of the day
    plt.gca().xaxis.set_major_formatter(DateFormatter('%H:%M'))
    plt.xticks(rotation=45)  # Rotate labels for better readability

    # Annotate the plot with RMSE and max outside air temperature
    plt.annotate(f'RMSE: {rmse:.4f}', xy=(0.05, 0.95), xycoords='axes fraction', fontsize=12)
    plt.annotate(f'Max OaTemp: {max_oa_temp:.2f}', xy=(0.05, 0.90), xycoords='axes fraction', fontsize=12)
    
    plt.tight_layout()
    #plt.show()
    plt.savefig('zoom_plot_with_predictions.png')

# Paths to the model and new data
model_path = 'best_chiller_delta_temp_model.pkl'
new_data_path = 'C:/Users/bbartling/Documents/WPCRC_Future.csv'

# Best lag value obtained from the previous script
best_lag = 5

# Predict and evaluate on the new data
predict_and_evaluate(model_path, new_data_path, best_lag)
