# Air Handling Unit

This is a Python based FDD tool for running fault equations HVAC systems across historical datasets with the Pandas computing library. Word documents are generated programmatically with the Python Docx library.

* Under the hood of the `FaultCondition` class, a method called apply (a Python function inside a class) processes the data and returns a boolean flag as a Pandas DataFrame column (fc1_flag) if the fault condition is present. Below is an example of the apply method for Fault Condition 1, which detects a VAV AHU supply fan fault due to low duct static pressure while the fan is operating at near 100% speed.

* As of 7/24/24, a new feature has been added: `rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()`. This feature introduces a rolling sum condition to ensure that a fault is only triggered if 5 consecutive conditions are met in the data. For instance as shown below in the code, if the fan is operating near 100% speed and is not meeting the duct static setpoint, and data is captured every minute, the system requires 5 consecutive faults (or 5 minutes) before officially throwing a fan fault. This helps prevent false positives. The `rolling_window_size` param will be a adjustable value (default of 5) for tuning purposes which can be passed into the fault `FaultCondition` class via the config dictionary. 

```python
import pandas as pd
import pandas.api.types as pdtypes
from air_handling_unit.faults.fault_condition import FaultCondition

class FaultConditionOne(FaultCondition):
    """Class provides the definitions for Fault Condition 1."""

    def __init__(self, dict_):
        """
        :param dict_:
        """
        self.vfd_speed_percent_err_thres = float
        self.vfd_speed_percent_max = float
        self.duct_static_inches_err_thres = float
        self.duct_static_col = str
        self.supply_vfd_speed_col = str
        self.duct_static_setpoint_col = str
        self.troubleshoot_mode = bool  # default should be False
        self.rolling_window_size = int

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col]
        self.check_analog_pct(df, columns_to_check)

        df['static_check_'] = (
            df[self.duct_static_col] < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres)
        df['fan_check_'] = (
            df[self.supply_vfd_speed_col] >= self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres)

        # Combined condition check
        df["combined_check"] = df['static_check_'] & df['fan_check_']

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc1_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["static_check_"]
            del df["fan_check_"]
            del df["combined_check"]

        return df
```
	


## Example Word Doc Report
TODO when new PyPI version is ready
* a description of the fault equation
* a plot of the data created with matplotlib with sublots
* data statistics to show the amount of time that the data contains as well as elapsed in hours and percent of time for when the fault condition is `True` and elapsed time in hours for the fan motor runtime.
* a histagram representing the hour of the day for when the fault equation is `True`.
* sensor summary statistics filtered for when the AHU fan is running

## Get Setup
TODO when new PyPI version is ready

## AHU fault equation descriptions
* **Fault Condition 1**: Duct static pressure too low with fan operating near 100% speed
* **Fault Condition 2**: Mix temperature too low; should be between outside and return air
* **Fault Condition 3**: Mix temperature too high; should be between outside and return air
* **Fault Condition 4**: PID hunting; too many operating state changes between AHU modes for heating, economizer, and mechanical cooling
* **Fault Condition 5**: Supply air temperature too low should be higher than mix air
* **Fault Condition 6**: OA fraction too low or too high, should equal to design % outdoor air requirement
* **Fault Condition 7**: Supply air temperature too low in full heating
* **Fault Condition 8**: Supply air temperature and mix air temperature should be approx equal in economizer mode
* **Fault Condition 9**: Outside air temperature too high in free cooling without additional mechanical cooling in economizer mode
* **Fault Condition 10**: Outdoor air temperature and mix air temperature should be approx equal in economizer plus mech cooling mode
* **Fault Condition 11**: Outside air temperature too low for 100% outdoor air cooling in economizer cooling mode
* **Fault Condition 12**: Supply air temperature too high; should be less than mix air temperature in economizer plus mech cooling mode
* **Fault Condition 13**: Supply air temperature too high in full cooling in economizer plus mech cooling mode
* **Fault Condition 14**: Temperature drop across inactive cooling coil (requires coil leaving temp sensor)
* **Fault Condition 14**: Temperature rise across inactive heating coil (requires coil leaving temp sensor)

## TODO
Setup repository for general AHU system energy efficiency FDD's.
* **roque zones**: Find in the VAV system and count of `rogue zones` that could be potentially used in tunning trim and respond (T&R) logic.
* **Excessive reheat energy fault**: Find in VAV system via VAV box leaving air temperature sensors or reheat valve positions conditions where AHU is cooling and majority of reheat system is in a heating mode.
* **General AHU Supply Fan Optimization fault**: Find in VAV system via VAV box air damper positions if fan is not adjusting or trimming to meet demand.
* **General AHU Supply Air Temperature Setpoint fault**: Find in VAV system via optimized AHU discharge air setpoint via VAV box zone air temperature and setpoints (sensible loads) and outside air conditions (latent loads) if applicable in areas where dehumidification is required. 
* More? Please post a git issue or discussion! 
