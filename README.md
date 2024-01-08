# open-fdd

## This is a Python based FDD tool for running fault equations inspired by ASHRAE Guideline 36 for HVAC systems across historical datasets with the Pandas computing library. Word documents are generated programmatically with the Python Docx library.


* NEW JUNE 2023 - AI powered suggestions based on data analysis, see `air_handling_unit/final_reports` directory for examples! Also paste in your Open AI api key in the `api_key.py` file. Please provide feedback or suggestions as the prompt engineering is a work in progress! See example reports in the directory `air_handling_unit/final_reports` where Chat GPT AI is providing all of the `Suggestions based on data analysis` on the bottom of the report bodys. Using Chat GPT to provide insights isnt a complete finish processed feel free to email or use a git issue to know more. See `air_handling_unit_fdd` sub directory to see more.

* NEW JULY 2023 - Demand response measurment and verification calculations and reports for electricity power meters. See `demand_response_mv` sub directory to see more. 2 methods are currently used to calculate demand response electricity power reduction are 10 previous weekday averaged of the electrical load profile and 10 closest weekday weather days.


## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-510a0961/)

## License

【MIT License】

Copyright 2022 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
