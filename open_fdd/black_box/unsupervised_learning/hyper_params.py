import pandas as pd
from sklearn.model_selection import GridSearchCV
from sklearn.ensemble import IsolationForest
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import numpy as np


# Custom scoring function for GridSearchCV using silhouette score
def anomaly_silhouette_score(estimator, X):
    anomalies = estimator.fit_predict(X)
    if len(np.unique(anomalies)) > 1:
        score = silhouette_score(X, anomalies)
    else:
        score = -1
    return score


# Load data
data = pd.read_csv(r"C:\Users\bbartling\Documents\WPCRC_Master.csv")
data["timestamp"] = pd.to_datetime(data["timestamp"])
data["chiller_delta_temp"] = data["CWR_Temp"] - data["CWS_Temp"]
data = data.drop(
    columns=[
        "CWR_Temp",
        "CWS_Temp",
        "VAV2_6_SpaceTemp",
        "VAV2_7_SpaceTemp",
        "VAV3_2_SpaceTemp",
        "VAV3_5_SpaceTemp",
    ]
)

# Filter data where 'Sa_FanSpeed' is less than 10.0
data = data[data["Sa_FanSpeed"] < 10.0]

# Define groups
group_building_power = data[["timestamp", "CurrentKW", "OaTemp"]]
group_heat_vlv_cntrl = data[
    ["timestamp", "HW_Valve", "DischargeTemp", "Ma_Temp", "Sa_FanSpeed"]
]
group_cool_vlv_cntrl = data[
    ["timestamp", "CW_Valve", "DischargeTemp", "Ma_Temp", "Sa_FanSpeed"]
]
group_econ_cntrl = data[
    ["timestamp", "MaDampers", "RA_Temp", "Ma_Temp", "OaTemp", "Sa_FanSpeed"]
]
fan_static_press_cntrl = data[["timestamp", "SaStatic", "SaStaticSPt", "Sa_FanSpeed"]]

groups = {
    "Building Power": group_building_power,
    "Heat Valve Control": group_heat_vlv_cntrl,
    "Cool Valve Control": group_cool_vlv_cntrl,
    "Economizer Control": group_econ_cntrl,
    "Fan Static Pressure Control": fan_static_press_cntrl,
}


# Rule-based fault detection
def detect_faults(data):
    data["fault_heat_valve"] = (
        (data["HW_Valve"] > 0)
        & (data["DischargeTemp"] <= data["Ma_Temp"])
        & (data["Sa_FanSpeed"] > 0)
    ).astype(int)
    data["fault_cool_valve"] = (
        (data["CW_Valve"] > 0)
        & (data["DischargeTemp"] >= data["Ma_Temp"])
        & (data["Sa_FanSpeed"] > 0)
    ).astype(int)
    data["fault_economizer"] = (
        (data["MaDampers"] > 0)
        & (data["RA_Temp"] <= data["Ma_Temp"])
        & (data["OaTemp"] < data["Ma_Temp"])
        & (data["Sa_FanSpeed"] > 0)
    ).astype(int)
    return data


data = detect_faults(data)

for group_name, group in groups.items():
    print(f"Processing group: {group_name}")

    # Data preprocessing
    group_filtered = group.fillna(group.median())
    scaler = StandardScaler()
    data_normalized = scaler.fit_transform(group_filtered.drop(columns=["timestamp"]))

    # Perform PCA for dimensionality reduction
    pca = PCA(n_components=0.95)
    data_pca = pca.fit_transform(data_normalized)

    # Define the parameter grid for hyperparameter tuning
    param_grid = {
        "n_estimators": [50, 100, 150],
        "max_samples": ["auto", 0.6, 0.8, 1.0],
        "contamination": [0.01, 0.05, 0.1],
        "max_features": [0.5, 0.75, 1.0],
        "bootstrap": [False, True],
        "random_state": [42],
    }

    # Initialize the Isolation Forest model
    model = IsolationForest()

    # Set up GridSearchCV with custom scoring function
    grid_search = GridSearchCV(
        estimator=model,
        param_grid=param_grid,
        scoring=anomaly_silhouette_score,
        cv=5,
        n_jobs=-1,
        verbose=2,
    )

    # Fit GridSearchCV
    grid_search.fit(data_pca)

    # Output the best parameters and estimator
    print("Best Parameters: ", grid_search.best_params_)
    best_model = grid_search.best_estimator_

    # Predict anomalies using the best model
    group["anomaly"] = best_model.predict(data_pca)
    group["anomaly"] = group["anomaly"].map({1: 0, -1: 1})

    # Combine rule-based faults with anomalies
    group["combined_faults"] = (
        group["anomaly"]
        | data.loc[group.index, "fault_heat_valve"]
        | data.loc[group.index, "fault_cool_valve"]
        | data.loc[group.index, "fault_economizer"]
    )

    # Display the results
    print(group[["timestamp", "anomaly", "combined_faults"]])

    # Optional: Display the top anomalies for manual inspection
    top_anomalies = group[group["anomaly"] == 1]
    print(f"Top anomalies in {group_name}:")
    print(top_anomalies.head())

    # Optional: Display the detected faults
    top_faults = group[group["combined_faults"] == 1]
    print(f"Detected faults in {group_name}:")
    print(top_faults.head())
