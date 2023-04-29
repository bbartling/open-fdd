"""
input CSV file is the -i arg
exclude a fault equation with -e arg

Tested on Windows 10 Python 3.10.6

Run like this to exclude fault 6 4 and 9 for example
$ py -3.10 ./run_all.py -i ./ahu_data/Report_AHU7_Winter.csv -e 6 4 9

Output reports will be in the final_report directory
"""


# used for report name
AHU_NAME = "ahu7"

# timestamp column name
INDEX_COL_NAME = "Date"
DUCT_STATIC_COL = "ahu7_sap"
DUCT_STATIC_SETPOINT_COL = "ahu7_sap_sp"
SUPPLY_VFD_SPEED_COL = "ahu7_sfo"
MIX_AIR_TEMP_COL = "ahu7_mat"
OUTSIDE_AIR_TEMP_COL = "ahu7_oat"
SUPPLY_AIR_TEMP_COL = "ahu7_dat"
RETURN_AIR_TEMP_COL = "ahu7_rat"
HEAT_VALVE_COMMAND_COL = "ahu7_htg_vlv"
COOL_VALVE_COMMAND_COL = "ahu7_clg_vlv"
OUTSIDE_AIR_DAMPER_COMMAND_COL = "ahu7_oa_dpr"
SUPPLY_FAN_AIR_VOLUME_COL = "vav_total_flow"

SUPPLY_AIR_TEMP_SETPOINT_COL = "ahu7_dat_sp"
# Leaving air temp setpoint constant value
# If there is no data and but constant value
CONSTANT_LEAVE_TEMP_SP = False
CONSTANT_LEAVE_TEMP_SP_VAL = 55.0

# G36 params shouldnt need adjusting
# error threshold parameters
VFD_SPEED_PERCENT_ERR_THRES = 0.05
VFD_SPEED_PERCENT_MAX = 0.99
DUCT_STATIC_PRESS_ERR_THRES = 0.1
OUTSIDE_AIR_TEMP_ERR_THRES = 5.0
MIX_AIR_TEMP_ERR_THRES = 2.0
RETURN_AIR_TEMP_ERR_THRES = 2.0
SUPPLY_AIR_TEMP_ERR_THRES = 2.0
FAN_DELTA_TEMP_ERR_THRES = 2.0

# FC4 max AHU state changes per hour
DELTA_OS_MAX = 7
AHU_MIN_OA = 0.20

# FC6 min diff between return and outside air
# temp to evalulate econ error conditions
DELTA_TEMP_MIN = 10

# FC6 paramto compare design percent OA to actual
AIRFLOW_ERR_THRES = 0.3

# FC6 DESIGN OA FROM BLUE PRINTS CAUTION
# ABOUT BEING CORRECT IN UNITS FOR AIR VOLUME
AHU_DESIGN_OA = 2500

# this will produce extra print statements
TROUBLESHOOT_MODE = False
