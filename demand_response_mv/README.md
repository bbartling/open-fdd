# Demand Response Measurement and Verification

## This is a Python based reporting tool used to calculate power reduction for demand response events based on 10 previous weekday averaged electrical load profile or a 10 closest weather day.

Requires a processed .csv file for interval power data combined with hourly weather data. This repo contains an example of processing hourly weather data downloaded from [NOAA](https://www.ncdc.noaa.gov/cdo-web/datatools/lcd) combined with interval electricity meter. See directory `scripts` for example of processing raw data. Another requirement is a csv file about event information that would contain a column for the `Test Case #` which is used as an arg when running the `main.py`. Other required columns in the `eventInfo.csv` is a column `Suitable Baseline Day?` which `main.py` uses in determination for baseline data as well as seperate columns `Test Start` and `Test End` that represent an integer value for the hour of the day the DR event started and stopped. Please submit git issues for tips getting up and running.


### Example usage tested on Windows
```bash
# show plots when running scripts
> py -3.10  main.py --test_case_id 10A_4 --show_plots True

# run without showing plots
> py -3.10 main.py --test_case_id 10A_4

# use method of closest weather days, the default method is 10 previous weekdays
> py -3.10 main.py --test_case_id 10A_4 --method closest_weather_dates
```

### Example Word Doc Report
![Alt text](/demand_response_mv/images/dr_report.png)


## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-510a0961/)

## Licence

【MIT License】

Copyright 2022 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
