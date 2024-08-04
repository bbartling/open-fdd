# TODO 

Highly experimental INCOMPLETE "black box" approach to training a machine learning model on a chiller's delta temperature over time. If a machine learning model can be trained on the chiller cycling over time via the delta temperature calculation, can the model be used for fault detection purposes? This is a time series ML model that is a single input type of model which could be something similar to how stock prices are predicted but with additional data to support the analysis from a physics perspective.


## `chiller_delta_temp` as ML input var

In Python data is loaded into the `Pandas` computing library and a delta temperature is calculated as shown below which is used as the target ML learning variable and all other variables are used for training purposes. In HVAC design, mechanical engineers typically size the cooling system and select a chiller that best fits the application based on a specific delta temperature. The chiller must maintain an optimal delta temperature for efficiency purposes, as specified by the manufacturer.

```python
def load_and_prepare_data(filepath):
    """Load, clean, and preprocess the data."""
    df = pd.read_csv(filepath, parse_dates=['timestamp'], index_col='timestamp')
    df = df[(df['CWS_Temp'] != 0) & (df['CWR_Temp'] != 0)]
    df['chiller_delta_temp'] = df['CWR_Temp'] - df['CWS_Temp']
    make_plots(df)
    plot_correlation_matrix(df)
    df.drop(columns=['CWR_Temp', 'CWS_Temp'], inplace=True)
    print(df.columns)
    return df.dropna()
```

Other variables used to train the data-driven model are shown below. These variables provide valuable information from a 'physics' standpoint, illustrating how a chiller consumes electrical power and performs the task of providing mechanical cooling to building systems. This process is reflected in the chiller's `chiller_delta_temp`, given the outside air conditions and the cooling loads on the building systems.

```bash
Name: chiller_delta_temp, dtype: float64
Index(['HWR_value', 'HWS_value', 'Heat_Calls', 'Oa_Temp', 'OaTemp_Enable',
       'CWS_Freeze_SPt', 'CW_Valve', 'HW_Valve', 'DischargeTemp', 'Eff_DaSP',
       'RaHumidity', 'Ra_Temp', 'Ra_FanSpeed', 'OaTemp', 'Ma_Dampers',
       'Ma_Temp', 'SaStaticSPt', 'Sa_FanSpeed', 'SaTempSP', 'RaCO2',
       'SaStatic', 'CurrentKWHrs', 'CurrentKW', 'Eff_DaSPt', 'RaTemp',
       'MaLowSPt', 'MaDampers', 'SaStatic_SPt', 'SaTempSPt', 'CoolValve',
       'OA_Damper', 'MA_Temp', 'EffSetpoint', 'EaDamper', 'SpaceTemp',
       'RA_CO2', 'RA_Temp', 'VAV2_6_SpaceTemp', 'VAV2_7_SpaceTemp',
       'VAV3_2_SpaceTemp', 'VAV3_5_SpaceTemp', 'chiller_delta_temp'],
      dtype='object')

```

## Plots

For this experiment there about 6 months of data on 5-minute intervals. Possibly a more desireable scenorio would be experimenting on a years worth of data on a one minute rolling average.

![Alt text](open_fdd\black_box_model\chiller_temperature_descriptions.png)

Correlation Matrix:

![Alt text](open_fdd\black_box_model\feature_correlation_matrix.png)

## Predict on a new months data

![Alt text](open_fdd\black_box_model\zoom_plot_with_predictions.png)

## Test model on made up data
TODO create new script to test ML model on fake very erroneous input data just to see what the model outputs. 