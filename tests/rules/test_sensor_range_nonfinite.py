import numpy as np
import pandas as pd

from open_fdd.rules.cookbook_catalog import _sweep_range


def test_sv_range_flags_present_infinite_sensor_values():
    frame = pd.DataFrame({"zone-air-temp": [72.0, np.inf, -np.inf, np.nan]})
    mask = _sweep_range(frame, {}, 300.0)
    assert mask.tolist() == [False, True, True, False]
