# open-fdd air_handling_unit

## Examples


###### For metric unit datasets reference the `params` screenshots inside the `images` directory link shown above. ERR_THRESHOLD parameters in the example.py files need to modified accordlingly for metric units as defined in the `param` screenshots.

###### Required inputs in addition to a column name `Date` with a Pandas readable time stamp tested in the format of `12/22/2022  7:40:00 AM`:

###### fc1.py - Supply fan not meeting duct static setpoint near 100% fan speed. The strings passed into the `FaultConditionOne` and `FaultCodeOneReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1 through OS# 5.
```python
from faults import FaultConditionOne
from reports import FaultCodeOneReport

# G36 error thresold params
VFD_SPEED_PERCENT_ERR_THRES = 0.05
VFD_SPEED_PERCENT_MAX = 0.99
DUCT_STATIC_INCHES_ERR_THRES = 0.1

_fc1 = FaultConditionOne(
    VFD_SPEED_PERCENT_ERR_THRES,
    VFD_SPEED_PERCENT_MAX,
    DUCT_STATIC_INCHES_ERR_THRES,
    "duct_static",
    "supply_vfd_speed",
    "duct_static_setpoint",
)
_fc1_report = FaultCodeOneReport(
    VFD_SPEED_PERCENT_ERR_THRES,
    VFD_SPEED_PERCENT_MAX,
    DUCT_STATIC_INCHES_ERR_THRES,
    "duct_static",
    "supply_vfd_speed",
    "duct_static_setpoint",
)

df2 = _fc1.apply(df)
```
###### fc2.py - Mixing temp too high. The strings passed into the `FaultConditionTwo` and `FaultCodeTwoReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1 through OS# 5.
```python
from faults import FaultConditionTwo
from reports import FaultCodeTwoReport

# G36 error thresold params
OUTDOOR_DEGF_ERR_THRES = 5.
MIX_DEGF_ERR_THRES = 5.
RETURN_DEGF_ERR_THRES = 2.

_fc2 = FaultConditionTwo(
    OUTDOOR_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    RETURN_DEGF_ERR_THRES,
    "mat",
    "rat",
    "oat",
    "supply_vfd_speed"
)
_fc2_report = FaultCodeTwoReport(
    OUTDOOR_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    RETURN_DEGF_ERR_THRES,
    "mat",
    "rat",
    "oat",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc2.apply(df)
```
###### fc3.py - Mixing temp too high. The strings passed into the `FaultConditionTwo` and `FaultCodeTwoReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1 through OS# 5.
```python
from faults import FaultConditionThree
from reports import FaultCodeThreeReport

# G36 error thresold params
OUTDOOR_DEGF_ERR_THRES = 5.
MIX_DEGF_ERR_THRES = 5.
RETURN_DEGF_ERR_THRES = 2.


_fc3 = FaultConditionThree(
    OUTDOOR_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    RETURN_DEGF_ERR_THRES,
    "mat",
    "rat",
    "oat",
    "supply_vfd_speed"
)
_fc3_report = FaultCodeThreeReport(
    OUTDOOR_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    RETURN_DEGF_ERR_THRES,
    "mat",
    "rat",
    "oat",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc3.apply(df)
```

###### fc4.py - Control system excesses operating state. The Pandas library computes AHU control system state changes per hour based on the data that is driving the AHU outputs, like heating/cooling valves and air damper analog commands. The strings passed into the `FaultConditionFour` and `FaultCodeFourReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1 through OS# 5.
```python
from faults import FaultConditionFour
from reports import FaultCodeFourReport

# G36 error thresold params
DELTA_OS_MAX = 7

# ADJUST this param for the AHU MIN OA damper setpoint
# found on building automation system
AHU_MIN_OA = 20

_fc4 = FaultConditionFour(
    DELTA_OS_MAX,
    AHU_MIN_OA,
    "economizer_sig",
    "heating_sig",
    "cooling_sig",
    "supply_vfd_speed"
)

_fc4_report = FaultCodeFourReport(DELTA_OS_MAX)

# return a whole new dataframe with fault flag as new col
# data is resampled for hourly averages in df2
df2 = _fc4.apply(df)
```

###### fc5.py - Suppy air temp too low. The strings passed into the `FaultConditionFive` and `FaultCodeFiveReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1.
```python
from faults import FaultConditionFive
from reports import FaultCodeFiveReport

# G36 error thresold params
DELTA_T_SUPPLY_FAN = 2.
SUPPLY_DEGF_ERR_THRES = 2.
MIX_DEGF_ERR_THRES = 5.

_fc5 = FaultConditionFive(
    DELTA_T_SUPPLY_FAN,
    SUPPLY_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    "sat",
    "mat",
    "htg_vlv",
    "supply_vfd_speed"
)


_fc5_report = FaultCodeFiveReport(
    DELTA_T_SUPPLY_FAN,
    SUPPLY_DEGF_ERR_THRES,
    MIX_DEGF_ERR_THRES,
    "sat",
    "mat",
    "htg_vlv",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc5.apply(df)
```

###### fc6.py - OA fraction too high. The strings passed into the `FaultConditionSix` and `FaultCodeSixReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1 and OS# 4. Note this equation requires calculating total supply air flow from all VAV boxes in the AHU system if the AHU doesnt have an air flow measuring station (AFMS). Also input design outdoor air found from blue print mechanical schedules for parameter `AHU_MIN_CFM_STP `.
```python
from faults import FaultConditionSix
from reports import FaultCodeSixReport

# G36 error thresold params
OAT_DEGF_ERR_THRES = 5
RAT_DEGF_ERR_THRES = 2
DELTA_TEMP_MIN = 10
AIRFLOW_ERR_THRES = .3

# OA design ventilation setpoint in CFM
# NEEDS to be modified from blue prints
AHU_MIN_CFM_STP = 3000

_fc6 = FaultConditionSix(
    AIRFLOW_ERR_THRES,
    AHU_MIN_CFM_DESIGN,
    OAT_DEGF_ERR_THRES,
    RAT_DEGF_ERR_THRES,
    DELTA_TEMP_MIN,
    AHU_MIN_OA_DPR,
    "vav_total_flow",
    "mat",
    "oat",
    "rat",
    "supply_vfd_speed",
    "economizer_sig",
    "heating_sig",
    "cooling_sig"
)

_fc6_report = FaultCodeSixReport(
    "vav_total_flow",
    "mat",
    "oat",
    "rat",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc6.apply(df)
```

###### fc7.py - Supply air temp too low. The strings passed into the `FaultConditionSeven` and `FaultCodeSevenReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 1.
```python
from faults import FaultConditionSeven
from reports import FaultCodeSevenReport

# G36 error thresold params
SAT_DEGF_ERR_THRES = 2

_fc7 = FaultConditionSeven(
    SAT_DEGF_ERR_THRES,
    "sat",
    "satsp",	
    "htg",
    "supply_vfd_speed"
)

_fc7_report = FaultCodeSevenReport(    
    "sat",
    "satsp",	
    "htg",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc7.apply(df)
```

###### fc8.py - Supply and mix air should be approx equal. The strings passed into the `FaultConditionEight` and `FaultCodeEightReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 2.
```python
from faults import FaultConditionEight
from reports import FaultCodeEightReport

# G36 error thresold params
DELTA_SUPPLY_FAN = 2
MIX_DEGF_ERR_THRES = 5
SUPPLY_DEGF_ERR_THRES = 2

_fc8 = FaultConditionEight(
    DELTA_SUPPLY_FAN,
    MIX_DEGF_ERR_THRES,
    SUPPLY_DEGF_ERR_THRES,
    "mat",
    "sat",
    "economizer_sig",
    "cooling_sig"
)

_fc8_report = FaultCodeEightReport(    
    "mat",
    "sat",
    "supply_vfd_speed",
    "economizer_sig"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc8.apply(df)
```

###### fc9.py - Outside air temp too high for free cooling without additional mechanical cooling. The strings passed into the `FaultConditionNine` and `FaultCodeNineReport` represent the csv file column names and required inputs for the given fault code.  Applies to OS# 2.
```python
from faults import FaultConditionNine
from reports import FaultCodeNineReport

# G36 error thresold params
DELTA_SUPPLY_FAN = 2
OAT_DEGF_ERR_THRES = 5
SUPPLY_DEGF_ERR_THRES = 2

_fc9 = FaultConditionNine(
    DELTA_SUPPLY_FAN,
    OAT_DEGF_ERR_THRES,
    SUPPLY_DEGF_ERR_THRES,
    "satsp",
    "oat",
    "cooling_sig",
    "economizer_sig",
)

_fc9_report = FaultCodeNineReport(    
    "satsp",
    "oat",
    "supply_vfd_speed",
    "economizer_sig"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc9.apply(df)
```

###### fc10.py - Outside and mix air temp should be approx equal. The strings passed into the `FaultConditionTen` and `FaultCodeTenReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 3.
```python
from faults import FaultConditionTen
from reports import FaultCodeTenReport

# ADJUST this param for the AHU MIN OA damper setpoint
# found on building automation system
AHU_MIN_OA = 20

# G36 error thresold params
OAT_DEGF_ERR_THRES = 5
MAT_DEGF_ERR_THRES = 5

_fc10 = FaultConditionTen(
    OAT_DEGF_ERR_THRES,
    MAT_DEGF_ERR_THRES,
    "mat",
    "oat",
    "clg",
    "economizer_sig",
)

_fc10_report = FaultCodeTenReport(    
    "mat",
    "oat",
    "clg",
    "economizer_sig",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc10.apply(df)
```

###### fc11.py - Outside air temp too low for 100% OA cooling. The strings passed into the `FaultConditionEleven` and `FaultCodeElevenReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 3.
```python
from faults import FaultConditionEleven
from reports import FaultCodeElevenReport

# G36 error thresold params
DELTA_SUPPLY_FAN = 2
OAT_DEGF_ERR_THRES = 5
SUPPLY_DEGF_ERR_THRES = 2

_fc11 = FaultConditionEleven(
    DELTA_SUPPLY_FAN,
    OAT_DEGF_ERR_THRES,
    SUPPLY_DEGF_ERR_THRES,
    "satsp",
    "oat",
    "clg",
    "economizer_sig"
)

_fc11_report = FaultCodeElevenReport(    
    "satsp",
    "oat",
    "clg",
    "economizer_sig",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc11.apply(df)
```

###### fc12.py - Supply air too high; should be less than mix air temp. The strings passed into the `FaultConditionTwelve` and `FaultCodeTwelveReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 3 and OS#4.
```python
from faults import FaultConditionTwelve
from reports import FaultCodeTwelveReport

# ADJUST this param for the AHU MIN OA damper setpoint
# found on building automation system
AHU_MIN_OA = 20

# G36 error thresold params
DELTA_SUPPLY_FAN = 2
MIX_DEGF_ERR_THRES = 5
SUPPLY_DEGF_ERR_THRES = 2

_fc12 = FaultConditionTwelve(
    DELTA_SUPPLY_FAN,
    MIX_DEGF_ERR_THRES,
    SUPPLY_DEGF_ERR_THRES,
    AHU_MIN_OA,
    "sat",
    "mat",
    "clg",
    "economizer_sig"
)

_fc12_report = FaultCodeTwelveReport(    
    "sat",
    "mat",
    "clg",
    "economizer_sig",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc12.apply(df)
```

###### fc13.py - Supply air temp too high in full cooling. The strings passed into the `FaultConditionTwelve` and `FaultCodeTwelveReport` represent the csv file column names and required inputs for the given fault code. Applies to OS# 3 and OS#4.
```python
from faults import FaultConditionThirteen
from reports import FaultCodeThirteenReport

# ADJUST this param for the AHU MIN OA damper setpoint
# found on building automation system
AHU_MIN_OA = 20

# G36 error thresold params
SAT_DEGF_ERR_THRES = 2

_fc13 = FaultConditionThirteen(
    SAT_DEGF_ERR_THRES,
    AHU_MIN_OA,
    "sat",
    "satsp",	
    "clg",
    "economizer_sig",
)

_fc13_report = FaultCodeThirteenReport(    
    "sat",
    "satsp",	
    "clg",
    "economizer_sig",
    "supply_vfd_speed"
)

# return a whole new dataframe with fault flag as new col
df2 = _fc13.apply(df)
```

### Other caveats is G36 does not mention anything about if the AHU is running or not. It could be wise to ignore any faults created when the AHU is not running or fan status/command equals `False` or fan VFD speeds equal 0%. G36 also expects data to be on one minute intervals and that a 5 minute rolling average be used in the analysis. The rolling average is handled by the Pandas computing library when the data file in CSV format is read into memory:

```python
df = pd.read_csv(args.input,
                 index_col='Date',
                 parse_dates=True).rolling('5T').mean()
```
