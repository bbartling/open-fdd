"""
input CSV file is the -i arg
exclude a fault equation with -e arg

Windows 10 Python 3.10
Run like this to exclude fault 6 4 and 9 for example
$ python3.10 ./run_all.py -i ./ahu_data/MZVAV-1.csv -d 4 6 9

OR another Windows run style:
$ py -3.10 ./run_all.py -i ./ahu_data/MZVAV-1.csv -d 4 6 9

Linux Python 3.10
$ python3.10 ./run_all.py -i ./ahu_data/MZVAV-1.csv -e 6

Output reports will be in the final_report directory
"""

config_dict = {
    # used for report name
    'AHU_NAME': "MZVAV_1",

    # timestamp column name
    'INDEX_COL_NAME': "Date",
    'DUCT_STATIC_COL': "AHU: Supply Air Duct Static Pressure",
    'DUCT_STATIC_SETPOINT_COL': "AHU: Supply Air Duct Static Pressure Set Point",
    'SUPPLY_VFD_SPEED_COL': "AHU: Supply Air Fan Speed Control Signal",
    'MAT_COL': "AHU: Mixed Air Temperature",
    'OAT_COL': "AHU: Outdoor Air Damper Control Signal",
    'SAT_COL': "AHU: Supply Air Temperature",
    'RAT_COL': "AHU: Return Air Temperature",
    'HEATING_SIG_COL': "AHU: Heating Coil Valve Control Signal",  # aka Heat Valve Command Col
    'COOLING_SIG_COL': "AHU: Cooling Coil Valve Control Signal",  # aka Cool Valve Command Col or clg_col
    'ECONOMIZER_SIG_COL': "AHU: Outdoor Air Damper Control Signal",    # aka Outside Air Damper Command Col
    'SUPPLY_FAN_AIR_VOLUME_COL': "vav_total_flow", # not provided in default data set

    'SAT_SETPOINT_COL': "AHU: Supply Air Temperature Set Point",
    # Leaving air temp setpoint constant value
    # If there is no data and but constant value
    'CONSTANT_LEAVE_TEMP_SP': False,
    'CONSTANT_LEAVE_TEMP_SP_VAL': 55.0,

    # G36 params shouldnt need adjusting
    # error threshold parameters
    'VFD_SPEED_PERCENT_ERR_THRES': 0.05,
    'VFD_SPEED_PERCENT_MAX': 0.99,
    'DUCT_STATIC_INCHES_ERR_THRES': 0.1,
    'OUTDOOR_DEGF_ERR_THRES': 5.0,
    'MIX_DEGF_ERR_THRES': 2.0,  # aka mixed air temp error threshold
    'RETURN_DEGF_ERR_THRES': 2.0,  # etc
    'SUPPLY_DEGF_ERR_THRES': 2.0,  # etc
    'DELTA_T_SUPPLY_FAN': 2.0,  # aka Fan Delta Temp Err Thres, also aka "delta_supply_fan" (FC8, 11).

    # FC4 max AHU state changes per hour
    'DELTA_OS_MAX': 7,

    # BAS setpoint for MIN OA DPR setpoint
    # set as a float 20% MIN OA would
    # be 0.20
    'AHU_MIN_OA_DPR': 0.20,
    # Note: this (min damper position) is NOT the same as min oa ratio

    # FC6 min diff between return and outside air
    # temp to evalulate econ error conditions
    'OAT_RAT_DELTA_MIN': 10,     # aka Delta Temp Min

    # FC6 paramto compare design percent OA to actual
    'AIRFLOW_ERR_THRES': 0.3,

    # FC6 DESIGN OA FROM BLUE PRINTS CAUTION
    # ABOUT BEING CORRECT IN UNITS FOR AIR VOLUME
    'AHU_MIN_OA_CFM_DESIGN': 2500,  # aka AHU Design OA
    # ToDo: sure you can load this from prints, but in actuality it will be set by the balancing contractor after
    #  construction and before turn-over. Review this in GL36.

    # this will produce extra print statements
    'TROUBLESHOOT_MODE': True
}