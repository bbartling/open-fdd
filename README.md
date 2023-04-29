# open-fdd

## This is a Python based FDD tool for running fault equations defined by ASHRAE Guideline 36 for HVAC systems across historical datasets with the Pandas computing library. G36 for air handling units (AHU's) there are 15 fault equations the first 13 of which are broken into seperate .py files, see ahu sub folder. 
Reference AHU fault equations and algorithm threshold parameters that are dependent on engineering units (I.E., Imperial Vs SI) here in your CSV file here:
* https://github.com/bbartling/open-fdd/tree/master/air_handling_unit/images

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


###### To run all AHU rules
```bash
$ git clone https://github.com/bbartling/open-fdd.git
$ cd open-fdd
$ pip install -r requirements.txt
$ cd air_handling_unit
```

###### Modify with text editor `run_all_config.py` for proper column names in your CSV file, G36 fault equation threshold parameters for proper units your CSV file contains (reference params images), and any necessary Boolean flag for troubleshooting.
```python
"""
input CSV file is the -i arg
exclude a fault equation with -e arg

Tested on Windows 10 Python 3.10.6

Run like this to exclude fault 6 4 and 9 for example
$ py -3.10 ./run_all.py -i ./ahu_data/Report_AHU7_Winter.csv -e 6 4 9

Output Word Doc reports will be in the final_report directory
"""
```

###### Note - Fault equations expect a float between 0.0 and 1.0 for a control system analog output that is typically expressed in industry HVAC controls as a percentage between 0 and 100% of command. Examples of a analog output could a heating valve, air damper, or fan VFD speed. For sensor input data these can be either float or integer based. Boolean on or off data for control system binary commands the fault equation expects an integer of 0 for Off and 1 for On. A column in your CSV file needs to be named `Date` with a Pandas readable time stamp tested in the format of `12/22/2022  7:40:00 AM`:

### More to come to incorporate G36 central cooling and heating plants (See PDF 2021 G36 that includes these equations in the PDF folder). Please submit a github issue or start a github conservation to request additional features. Pull requests encouraged to promote a community based free open source tool to help promote ASHRAE, HVAC optimization, and building carbon reduction efforts.

## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-510a0961/)

## Licence

【MIT License】

Copyright 2022 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
