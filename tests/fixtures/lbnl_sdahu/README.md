# LBNL single-duct AHU fixture (derived, tiny)

Two days (2018-07-03 and 2018-07-10, 5-minute rows, the 13 columns `open_fdd.ml.lbnl` maps) from two files of the
LBNL FDD data library, single-duct AHU (simulated): `AHU_annual.csv` (fault-free) and `coi_stuck_050_annual.csv`
(cooling coil valve stuck at 50 %). Values are as published (°F, 0-1, mixed static-pressure units), rounded to five
significant digits. Used only by `tests/test_ml_fdd.py`; the benchmark downloads the full files into a cache.

Source and license: Lawrence Berkeley National Laboratory, *LBNL FDD Data Sets*, https://faultdetection.lbl.gov/data/ ,
DOI https://doi.org/10.25984/1881324 . Granderson, J., Lin, G., Chen, Y., Casillas, A., Huang, S., Vrabie, D. (2022).
Licensed under Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/). Changes: subset of
rows and columns, rounding.
