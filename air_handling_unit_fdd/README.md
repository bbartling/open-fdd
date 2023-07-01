# AHU

## This is a Python based FDD tool for running fault equations inspired by ASHRAE Guideline 36 for HVAC systems across historical datasets with the Pandas computing library. Word documents are generated programmatically with the Python Docx library.

Using Chat GPT to provide insights is optional and isnt a completely finish processed feel free to email or use a git issue to know more.

###### Under the hood of a `FaultCondition` class a method (Python function inside a class) called `apply` looks like this below as an example shown for the fault condition 1 which returns the boolean flag as a Pandas dataframe column (`fc1_flag`) if the fault condition is present:
```python
def apply(self, df: pd.DataFrame) -> pd.DataFrame:
    df['static_check_'] = (
        df[self.duct_static_col] < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres)
    df['fan_check_'] = (df[self.supply_vfd_speed_col] >=
                        self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres)

    df["fc1_flag"] = (df['static_check_'] & df['fan_check_']).astype(int)

    return df
```
	
###### A report is generated using the Python docx library from passing data into the `FaultCodeReport` class will output a Word document to a directory containing the following info, currently tested on a months worth of data.
* a description of the fault equation
* a snip of the fault equation as defined by ASHRAE
* a plot of the data created with matplotlib with sublots
* data statistics to show the amount of time that the data contains as well as elapsed in hours and percent of time for when the fault condition is `True` and elapsed time in hours for the fan motor runtime.
* a histagram representing the hour of the day for when the fault equation is `True`.
* sensor summary statistics filtered for when the AHU fan is running

### Example Word Doc Report
![Alt text](/air_handling_unit_fdd/images/fc1_report_screenshot_all.png)

### Get Setup
```bash
$ git clone https://github.com/bbartling/open-fdd.git
$ cd open-fdd
$ pip install -r requirements.txt
$ cd air_handling_unit_fdd
```

### Modify with text editor `run_all_config.py`
* set proper column names in your CSV file 
* threshold params need to be engineering unit specific for Imperial or SI units, see `params` screenshot in the images directory
* input arg for CSV file path is `-i`
* input arg for 'do' is `-d` which represents which fault to 'do'
* tested on Windows 10 and Ubuntu 20 LTS on Python 3.10
* output Word Doc reports will be in the final_report directory

```python
# 'do' fault 1 and 2 for example
$ python ./run_all.py -i ./ahu_data/MZVAV-1.csv -d 1 2
```

## Fault equation descriptions
* Fault Condition 1: Duct static pressure too low with fan operating near 100% speed
* Fault Condition 2: Mix temperature too low; should be between outside and return air
* Fault Condition 3: Mix temperature too high; should be between outside and return air
* Fault Condition 4: PID hunting; too many operating state changes between AHU modes for heating, economizer, and mechanical cooling
* Fault Condition 5: Supply air temperature too low should be higher than mix air
* Fault Condition 6: OA fraction too low or too high, should equal to design % outdoor air requirement
* Fault Condition 7: Supply air temperature too low in full heating
* Fault Condition 8: Supply air temperature and mix air temperature should be approx equal in economizer mode
* Fault Condition 9: Outside air temperature too high in free cooling without additional mechanical cooling in economizer mode
* Fault Condition 10: Outdoor air temperature and mix air temperature should be approx equal in economizer plus mech cooling mode
* Fault Condition 11: Outside air temperature too low for 100% outdoor air cooling in economizer cooling mode
* Fault Condition 12: Supply air temperature too high; should be less than mix air temperature in economizer plus mech cooling mode
* Fault Condition 13: Supply air temperature too high in full cooling in economizer plus mech cooling mode
* Fault Condition 14: Temperature drop across inactive cooling coil (requires coil leaving temp sensor)
* Fault Condition 14: Temperature rise across inactive heating coil (requires coil leaving temp sensor)

###### Note - Fault equations expect a float between 0.0 and 1.0 for a control system analog output that is typically expressed in industry HVAC controls as a percentage between 0 and 100% of command. Examples of a analog output could a heating valve, air damper, or fan VFD speed. For sensor input data these can be either float or integer based. Boolean on or off data for control system binary commands the fault equation expects an integer of 0 for Off and 1 for On. A column in your CSV file needs to be named `Date` with a Pandas readable time stamp tested in the format of `12/22/2022  7:40:00 AM`:

### More to come to incorporate AHU zone level faults, fuel meters, central cooling and heating plants. Please submit a github issue or start a github conservation to request additional features. Pull requests encouraged to promote a community based free open source tool to help promote better buildings, commissioning professionals, HVAC optimization, and building carbon reduction efforts.

## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-510a0961/)

## Licence

【MIT License】

Copyright 2022 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
