# BRICK and SQL experiment

TODO make writeup on sqlite, BRICK rdf, and running a fault rule based on query for meta data.

Notes for `3_run_query_fc1_brick.py` on updating the database for a faults after fault logic runs.
```python
Total faults detected: 0
Starting batch update...
Doing batch 0
Batch 1 completed: 1000 records updated in 0 minutes and 32 seconds
Doing batch 1000
Batch 2 completed: 1000 records updated in 1 minutes and 11 seconds
Doing batch 2000
Batch 3 completed: 1000 records updated in 2 minutes and 24 seconds
Doing batch 3000
Batch 4 completed: 1000 records updated in 3 minutes and 42 seconds
Doing batch 4000
Batch 5 completed: 1000 records updated in 4 minutes and 31 seconds
Doing batch 5000
Batch 6 completed: 1000 records updated in 5 minutes and 16 seconds
Doing batch 6000
Batch 7 completed: 1000 records updated in 5 minutes and 54 seconds
Doing batch 7000
Batch 8 completed: 1000 records updated in 6 minutes and 28 seconds
Doing batch 8000
Batch 9 completed: 900 records updated in 7 minutes and 3 seconds
Batch update completed.
Total records updated: 8900
Total time taken: 7 minutes and 3 seconds
Records per minute: 1262.03
columns: 
 Index(['Supply_Air_Static_Pressure_Sensor',
       'Supply_Air_Static_Pressure_Setpoint', 'Supply_Fan_VFD_Speed_Sensor',
       'static_check_', 'fan_check_', 'combined_check', 'fc1_flag'],
      dtype='object')
```

