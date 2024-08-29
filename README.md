# open-fdd

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version)


![Alt text](https://raw.githubusercontent.com/bbartling/open-fdd/master/open_fdd/air_handling_unit/images/plot_for_repo.png)


This is a Python-based Fault Detection and Diagnostics (FDD) tool for running fault equations inspired by ASHRAE and NIST standards for HVAC systems across historical datasets using the Pandas computing library. The tool evaluates various fault conditions and outputs fault flags as boolean columns within typical Pandas DataFrames. These fault flags indicate the presence (True) or absence (False) of specific issues identified by the fault equations. This approach integrates seamlessly into standard data science and computer science workflows, allowing for efficient analysis, visualization, and further processing of fault conditions within familiar data structures like DataFrames.


## Getting Setup
This project is now available on PyPI, making it easy to set up with the Python package manager, pip. You can install the package using the following command:

```bash
pip install open-fdd
```

For running Jupyter notebooks, I recommend using Visual Studio Code with the Jupyter notebook extension installed, which offers a seamless experience directly within the editor. Be sure to explore the `examples` directory for Jupyter notebook tutorials. If you have your own FDD experiences to share, feel free to contribute by creating a notebook (`.ipynb`). You’re welcome to reach out to me directly, and I can push your example to GitHub on your behalf, which might be a simpler process than submitting a pull request (PR), especially if you're just sharing an example rather than developing `open-fdd`.

## Project goals
The following are key objectives to enhance this project into a fully interactive Fault Detection and Diagnostics (FDD) application.

### Completed
 - [x] Develop and finalize `air_handling_unit` fault conditions and reports, aligning with ASHRAE and NIST standards.
 - [x] Publish the project as a Python library on PyPI.

### In Progress
 - [ ] Create IPython notebook tutorials showcasing AHU FDD examples, incorporating BRICK metadata integration.
 - [ ] Extend the project to include `central_plant` fault conditions, IPython reports, and example applications for boiler and chiller systems.


### Upcoming
 - [ ] Design `energy_efficiency` fault detection modules, including IPython reports and examples focused on optimizing energy consumption.
 - [ ] Develop `metering` fault conditions, along with IPython reports and examples, potentially modeling utility metering data.
 - [ ] Implement SQL integration examples for reading data from a time series database, writing back to SQL, and visualizing faults in Grafana.

### Future Considerations
 Explore additional features and enhancements as the project evolves.
 - [ ] Explore additional features and enhancements as the project evolves.
 - [ ] Develop a comprehensive guide on a github.io website (or other?) for defining fault parameters, including error thresholds and other critical settings.


## Contribute
If you have suggestions for improving developer best practices or solutions, please feel free to reach out to me directly using my contact information or Git issue/discussion. I primarily work on Windows with multiple versions of Python installed, with Python 3.12.x as my default version. You can download the latest version of Python here:
* https://www.python.org/downloads/

1. **Adding New Faults and Reports:**  
   Developers will need to `> py -3.12 -m pip install black pytest`. When adding new faults and reports, I usually run `> py -3.12 -m pip install .` in the cloned project directory. I continuously uninstall with `> py -3.12 -m pip uninstall open-fdd` and reinstall locally until I'm satisfied with the changes.

2. **Testing Fault Logic:**  
   All fault logic is rigorously tested using `pytest`. You can run the tests with `> py -m pytest`.

3. **Formatting with Black:**  
   To ensure code consistency, I use Black for formatting. Run `> py -m black .` to format the code and check it with `> py -m black --check .`

4. **Pushing to GitHub:**  
   After making changes, and the steps above are successful push them to GitHub in a pull request. The GitHub Actions workflow will automatically run `pytest` and `black` to ensure the build is successful.


This project is a community-driven initiative, focusing on the development of free and open-source tools. I believe that Fault Detection and Diagnostics (FDD) should be free and accessible to anyone who wants to try it out, embodying the spirit of open-source philosophy. Additionally, this project aims to serve as an educational resource, empowering individuals to learn about and implement FDD in their own systems. As someone wisely said, `"Knowledge should be shared, not hoarded,"` and this project strives to put that wisdom into practice.

Got any ideas or questions? Submit a Git issue or start a Discussion...

## License

【MIT License】

Copyright 2024 Ben Bartling

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
