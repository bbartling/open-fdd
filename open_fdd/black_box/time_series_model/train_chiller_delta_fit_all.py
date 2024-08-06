import pandas as pd
import numpy as np
from sklearn.ensemble import AdaBoostRegressor, RandomForestRegressor, GradientBoostingRegressor, BaggingRegressor, ExtraTreesRegressor, VotingRegressor
from sklearn.tree import DecisionTreeRegressor
from sklearn.linear_model import LinearRegression
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
import joblib
import matplotlib
matplotlib.use('Agg')  # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
import seaborn as sns
import time

# Base estimator for AdaBoost and Bagging
base_estimator = DecisionTreeRegressor(max_depth=4)

def create_lagged_features(df, lag):
    """Create lagged features for a DataFrame for all columns."""
    lagged_df = pd.concat([df.shift(i) for i in range(1, lag + 1)], axis=1)
    new_cols = [f'{col}_lag{i}' for i in range(1, lag + 1) for col in df.columns]
    lagged_df.columns = new_cols
    return pd.concat([df, lagged_df], axis=1).dropna()

def make_plots(df):
    # Describe and plot key temperatures
    print(df[['CWS_Temp', 'CWR_Temp', 'chiller_delta_temp']].describe())
    fig, axes = plt.subplots(2, 1, figsize=(15, 10))
    df['CWS_Temp'].plot(ax=axes[0], kind='line', color='blue', label='CWS_Temp')
    df['CWR_Temp'].plot(ax=axes[0], kind='line', color='red', label='CWR_Temp')
    axes[0].legend()
    df['chiller_delta_temp'].plot(ax=axes[1], kind='line', color='green', title='Chiller Delta Temp')
    plt.tight_layout()
    plt.savefig('chiller_temperature_descriptions.png')

def plot_correlation_matrix(df):
    # Correlation matrix heatmap
    plt.figure(figsize=(15, 10))
    correlation_matrix = df.corr()
    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', fmt=".2f", annot_kws={"size": 8})
    plt.title('Feature Correlation Matrix')
    plt.tight_layout()
    plt.savefig('feature_correlation_matrix.png')

def load_and_prepare_data(filepath):
    """Load, clean, and preprocess the data."""
    df = pd.read_csv(filepath, parse_dates=['timestamp'], index_col='timestamp')
    df = df[(df['CWS_Temp'] != 0) & (df['CWR_Temp'] != 0)]
    df['chiller_delta_temp'] = df['CWR_Temp'] - df['CWS_Temp']
    make_plots(df)  # Call make_plots before dropping columns
    plot_correlation_matrix(df)
    df.drop(columns=['CWR_Temp', 'CWS_Temp'], inplace=True)
    print(df.columns)
    return df.dropna()

def evaluate_lags(df, max_lag):
    """Evaluate different lags to find the best based on RMSE."""
    best_rmse = np.inf
    best_lag = None
    best_model = None
    best_model_type = None
    fastest_model = None
    fastest_model_type = None
    fastest_fit_time = np.inf
    
    models = {
        'AdaBoost': AdaBoostRegressor(estimator=base_estimator, n_estimators=100, random_state=42),
        'RandomForest': RandomForestRegressor(n_estimators=100, random_state=42),
        'GradientBoosting': GradientBoostingRegressor(n_estimators=100, random_state=42),
        'Bagging': BaggingRegressor(estimator=base_estimator, n_estimators=100, random_state=42),
        'ExtraTrees': ExtraTreesRegressor(n_estimators=100, random_state=42),
        'Voting': VotingRegressor([
            ('rf', RandomForestRegressor(n_estimators=100, random_state=42)),
            ('gbr', GradientBoostingRegressor(n_estimators=100, random_state=42)),
            ('svr', SVR())
        ])
    }
    
    for lag in range(1, max_lag + 1):
        temp_df = create_lagged_features(df, lag)
        train_df, test_df = train_test_split(temp_df, test_size=0.2, random_state=42)
        
        for model_name, model in models.items():
            start_time = time.time()
            model.fit(train_df.drop('chiller_delta_temp', axis=1), train_df['chiller_delta_temp'])
            fit_time = time.time() - start_time
            predictions = model.predict(test_df.drop('chiller_delta_temp', axis=1))
            rmse = np.sqrt(mean_squared_error(test_df['chiller_delta_temp'], predictions))
            
            print(f"Lag: {lag}, Model: {model_name}, RMSE: {rmse}, Fit time: {fit_time:.2f}s")
            
            if rmse < best_rmse:
                best_rmse = rmse
                best_lag = lag
                best_model = model
                best_model_type = model_name
            
            if fit_time < fastest_fit_time:
                fastest_fit_time = fit_time
                fastest_model = model
                fastest_model_type = model_name
    
    return best_lag, best_model, best_model_type, best_rmse, fastest_model_type, fastest_fit_time

# Main execution flow
df = load_and_prepare_data("WPCRC_Master.csv")
best_lag, best_model, best_model_type, best_rmse, fastest_model_type, fastest_fit_time = evaluate_lags(df, 5)
print(f"The best lag found is: {best_lag}")
print(f"The best model type is: {best_model_type} with RMSE: {best_rmse}")
print(f"The fastest model to fit is: {fastest_model_type} with fit time: {fastest_fit_time:.2f}s")

# Prepare data with the best lag
df = create_lagged_features(df, best_lag)
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

# Train and save the best model
best_model.fit(train_df.drop('chiller_delta_temp', axis=1), train_df['chiller_delta_temp'])
joblib.dump(best_model, f'best_chiller_delta_temp_model_{best_model_type}.pkl')
