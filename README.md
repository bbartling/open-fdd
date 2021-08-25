# zip 
###### Pandas tool to chart daily electrical load profiles into Microsoft Word docs
 
 
Notes:
 
run `py -3.7 main.py City_Library_2019` in the command prompt (the name of the CSV file to analyze which was placed in the `sample_data` directory) and hit `ENTER`. Note this is the name of the CSV file without the .csv extension. CSV files are a requirement see note 7 for pre data processing in Excel prior to using Zip. All data files must be placed in the `sample_data` directory prior to running the script `main.py`.

 ![Alt text](https://github.com/bbartling/zip/blob/master/images/app.PNG)
 

Modify as necessary in Excel your utility provider supplied data files prior to running the script `main.py`. Only run 1 year of data at a time with Zip. Make the name of the CSV file simple that utilizes a `_` character instead of a ` ` (space) character. 

For example a filed named `School 2014 2015 KW` needs to be renamed something like `School_2014_2015_KW` with no spaces in the name of the file.


The Excel CSV files need to be formatted that the time stamp column is named `Date` and the electricity column is named `kW` as exactly demonstrated below. Zip looks for a columns named `Date` and `kW` anything different the script will resort to an exception error. 

![Alt text](https://github.com/bbartling/zip/blob/master/images/excel.PNG)

If your utility provider dataset has the time and date stamp in seperate columns use this as a reference for combining date and time into one column. 

Create an additional column in Excel with this code to combine date and time into one column name `Date`.

Excel column code:
`=TEXT(A2,"m/dd/yy ")&TEXT(B2,"hh:mm:ss")`
https://www.extendoffice.com/documents/excel/1538-excel-combine-date-and-time.html

Delete all other columns as necessary so your file looks like the screen shot above.

The file format requires a CSV file type extentions, make sure in Excel to save the file as a CSV as shown below.

![Alt text](https://github.com/bbartling/zip/blob/master/images/CSV.PNG)

Once your prepped utility provider file is in the `sample_data` directory, open up the command prompt and run `main.py` as stated in step 6. Allow for a few minutes for the script to execute the command prompt will show the execution state. Once finished navigate to the `final_report` directory to view results that will be compiled into a Microsoft Word document.

Zip data analysis uses the `ruptures` package to calculate changepoints in the electricity interval data. See https://github.com/deepcharles/ruptures for more detail about the change point process. Zip uses the dynamic programming method provided by Ruptures. See the `static_main` folder directory to view image files of the change point algorithm process used to rank days in the dataset. This is a visualation only to verify change point algorithm accuracy on the dataset.

![Alt text](https://github.com/bbartling/zip/blob/master/images/8.PNG)



## Author

[linkedin](https://www.linkedin.com/in/ben-bartling-cem-cmvp-510a0961/)

## Licence

【MIT License】

Copyright 2021 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
