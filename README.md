# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)


![Alt text](https://raw.githubusercontent.com/bbartling/open-fdd/master/open_fdd/air_handling_unit/images/plot_for_repo.png)


This is a Python-based Fault Detection and Diagnostics (FDD) tool for running fault equations inspired by ASHRAE and NIST standards for HVAC systems across historical datasets using the Pandas computing library. The tool evaluates various fault conditions and outputs fault flags as boolean columns within typical Pandas DataFrames. These fault flags indicate the presence (True) or absence (False) of specific issues identified by the fault equations. This approach integrates seamlessly into standard data science and computer science workflows, allowing for efficient analysis, visualization, and further processing of fault conditions within familiar data structures like DataFrames.


## Getting Setup
* Some features may be broken or not work as expected while the project is undergoing a significant makeover to become installable from PyPI. The aim is to streamline the reporting processes and make them much easier to use. I appreciate your patience during this transition.

This project is on PyPI now so get setup with this command using the Python package manager called pip.

```bash
pip install open-fdd
```

See the `examples` directory for Jupyter notebook tutorials.

## Project goals
These are some basic project goals to make this into an interactive FDD application.
 - [x] finish `air_handling_unit` faults and reports based on ASHRAE and NIST
 - [x] publish to PyPI as Python library
 - [ ] make a few IPython notebook tutorials AHU FDD examples with `BRICK` meta data integration.
 - [ ] make a guide for fault `parameters` like error thresholds, etc.
 - [ ] make `central_plant` faults, IPython reports, and examples.
 - [ ] make `energy_efficiency` faults, IPython reports, and examples to `optimize` in reducing energy consumption.
 - [ ] make `metering`, faults, IPython reports, and examples to possibly model utility metering data.
 - [ ] create SQL example to read data from time series db and write back to SQL to then read faults in Grafana.
 - [ ] other?

## Contribute
This project is a community-driven initiative, focusing on the development of free and open-source tools. I believe that Fault Detection and Diagnostics (FDD) should be free and accessible to anyone who wants to try it out, embodying the spirit of open-source philosophy. Additionally, this project aims to serve as an educational resource, empowering individuals to learn about and implement FDD in their own systems. As someone wisely said, `"Knowledge should be shared, not hoarded,"` and this project strives to put that wisdom into practice.

Got any ideas or questions? Submit a Git issue or start a Discussion...

## License

【MIT License】

Copyright 2024 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
