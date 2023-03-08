data_generate.py
===============

This script generates fake data based on a YAML configuration file and command-line arguments. The generated data can be saved to a CSV file for further analysis.

Usage
-----

To use this script, run the following command in a terminal or command prompt:

.. code-block:: bash

   python scripts/data_generate.py config.yaml <output_filename> --start_date <start_date> --periods <periods> --interval <interval> 
   
   python scripts/data_generator.py ahu_data/configs/fc1.yaml ahu_data/generated/fc1.csv
Where:

- ``config.yaml`` is the path to the configuration file that specifies the input specifications and other options for the data generation.
- ``<start_date>`` is the start date (YYYY-MM-DD) for the data generation. This argument is optional.  The default value is today.
- ``<periods>`` is the number of periods for the data generation. This argument is optional with approximately 1 month as the default in 1 min intervals - ie 60*24*31.
- ``<interval>`` is the frequency of the data generation, specified as a single letter code (1m=1 min interval, 15m=15 min interval). This argument is optional and defaults to "1m".
- ``<output_filename>`` is the name of the output file that will contain the generated data. This argument is optional and can be omitted if the output filename is specified in the configuration file.

Configuration file
------------------

The configuration file is a YAML file that specifies the input specifications and other options for the data generation. The file should have the following structure:

.. code-block:: yaml

   inputs:
     - name: <input_name_1>
       low: <low_value_1>
       high: <high_value_1>
       type: <data_type_1>
     - name: <input_name_2>
       low: <low_value_2>
       high: <high_value_2>
       type: <data_type_2>
     ...

Where:

- ``<input_name_i>`` is the name of the ith input variable.
- ``<low_value_i>`` and ``<high_value_i>`` are the lower and upper bounds of the ith input variable, respectively.
- ``<data_type_i>`` is the data type of the ith input variable (float, int, or date).

Output file
-----------

The output file is a CSV file that contains the generated data. Each row in the file corresponds to a single data point, and the columns correspond to the input variables and their values at that time point.

