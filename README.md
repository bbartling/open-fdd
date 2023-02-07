# open-fdd

###### Python based HVAC system fault detection reporting for air handling units (AHU) based on ASHRAE Guideline 36 2018, see PDF subfolder.

## G36 for AHU's has 15 fault equations the first 13 of which are broken into seperate .py files with the exception of combined fault 2 and 3. Fault equations 14 and 15 are ommitted for the time being as these are for AHU systems with heating cooling coil leaving temperature sensors that maybe not typical AHU type systems.

## Run the .py files in this fashion with specifying a data input argument `i` and a output argument `o` which will be the name of the report Word document that can be retrieved from the `final_report` directory after the script executes. Fault equation 6 is used as example:

`$python .\fc6.py -i ./ahu_data/hvac_random_fake_data/fc6_fake_data1.csv -o fake1_ahu_fc6_report`

## The final report should look like the following, currently tested on a months worth of data.
* a description of the fault equation
* a snip of the fault equation as defined by ASHRAE
* a plot of the data created with matplotlib with sublots
* data statistics to show the amount of time that the data contains as well as elapsed in hours and percent of time for when the fault condition is `True`.
* a histagram representing the hour of the day for when the fault equation is `True`.
* sensor summary statistics

## caveats in the present moment is the fault equations expect a pandas dataframe with the corresponding data frame column names unique to each fault equation and in °F. Future version can include degrees °C is there is the usecase. For example the fault equation 6 function is:

```shell
def fault_condition_six_(df):
    return operator.and_(df.rat_minus_oat >= df.oat_rat_delta_min,
                          df.percent_oa_calc_minus_perc_OAmin > df.airflow_err_thres
                         )
```

## Required inputs in addition to a column name `Date` with a Pandas readable time stamp tested with `12/22/2022  7:40:00 AM`:

### fc1.py
* `duct_static` (duct static pressure °F)
* `supply_vfd_speed` (suppy fan VFD speed reference %)
- note this equation assumes 1" of static pressure setpoint. Script should be modified to the duct pressure setpoint if it is fixed or another variable should be created for duct pressure setpoint if the data exists.

### fc2_3.py 
* `mat` (mixing air temperature °F)
* `rat` (return air temperature °F)
* `oat` (outside air temperature °F)

### fc4.py
* `heating_sig` (heating valve position or command %)
* `economizer_sig` (mixing air damper position or command %)
* `cooling_sig` (cooling valve position or command %)

`fc5.py`
* `heating_sig` (heating valve position or command %)
* `economizer_sig` (mixing air damper position or command %)
* `cooling_sig` (cooling valve position or command %)

`fc6.py`
* `mat` (mixing air temperature °F)
* `rat` (return air temperature °F)
* `oat` (outside air temperature °F)
* `vav_total_flow` (totalized vav box air flows CFM)

`fc7.py`
* `sat`	(supply air temperature °F)
* `satsp` (supply air temperature setpoint °F)
* `htg` (heating valve position or command %)

`fc8.py`
* `mat` (mixing air temperature °F)
* `sat`	(supply air temperature °F)

`fc9.py`
* `sat`	(supply air temperature °F)
* `oat` (outside air temperature °F)

`fc10.py`
* `oat` (outside air temperature °F)
* `mat` (mixing air temperature °F)

`fc11.py`
* `sat`	(supply air temperature °F)
* `oat` (outside air temperature °F)

`fc12.py`
* `sat`	(supply air temperature °F)
* `mat` (mixing air temperature °F)

`fc13.py`
* `sat`	(supply air temperature °F)
* `satsp` (supply air temperature setpoint °F)
* `clg` (cooling valve position or command %)

## other caveats is G36 expects data to be on one minute intervals and that a 5 minute rolling average be used in the analysis. The rolling average is handled by the Pandas computing library:

```shell
df = pd.read_csv(args.input,
                 index_col='Date',
                 parse_dates=True).rolling('5T').mean()
```
## More to come in the future to incorporate G36 central cooling and heating plants (See PDF folder). Please submit github issue or start a github convervation to request additional features. Pull requests incouraged to promote a community based free open source tool to help promote HVAC optimization and building carbon reduction.

## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-510a0961/)

## Licence

【MIT License】

Copyright 2022 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
