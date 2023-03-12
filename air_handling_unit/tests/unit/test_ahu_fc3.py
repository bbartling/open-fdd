from faults import FaultConditionThree
import random
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc3.py -rP

random seed set every time random.random()
is called so the results to be exact same
every time for the flag mean col output.

Future compare to ML FDD Vs rule based FDD
'''


TEST_OUTDOOR_DEGF_ERR_THRES = 5.
TEST_MIX_DEGF_ERR_THRES = 5.
TEST_RETURN_DEGF_ERR_THRES = 2.
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"


# mix air temp higher than out temp
def fail_row() -> dict:
    data = {
        TEST_MIX_TEMP_COL : 85.,
        TEST_RETURN_TEMP_COL : 72.,
        TEST_OUT_TEMP_COL : 55.,
        TEST_SUPPLY_VFD_SPEED_COL : .8,
    }
    return data


def pass_row() -> dict:
    data = {
        TEST_MIX_TEMP_COL : 60.,
        TEST_RETURN_TEMP_COL : 72.,
        TEST_OUT_TEMP_COL : 45.,
        TEST_SUPPLY_VFD_SPEED_COL : .8,
    }
    return data


def generate_data(fail_portion: float, samples: int) -> pd.DataFrame:
    data = []
    for _ in range(samples):
        random.seed(_)
        if random.random() < fail_portion:
            data.append(fail_row())
        else:
            data.append(pass_row())
    return pd.DataFrame(data)


@pytest.fixture
def failing_df() -> pd.DataFrame:
    return generate_data(0.9, 100)


@pytest.fixture
def passing_df() -> pd.DataFrame:
    return generate_data(0.1, 100)


def test_failing(failing_df):
    fc3 = FaultConditionThree(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_RETURN_DEGF_ERR_THRES,
    TEST_OUTDOOR_DEGF_ERR_THRES,
    TEST_MIX_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    results = fc3.apply(failing_df)
    actual = results["fc3_flag"].mean()
    expected = 0.89
    message = f"fc3 FAIL actual is {actual} and expected is {expected}"
    assert actual == pytest.approx(expected), message


def test_passing(passing_df):
    fc3 = FaultConditionThree(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_RETURN_DEGF_ERR_THRES,
    TEST_OUTDOOR_DEGF_ERR_THRES,
    TEST_MIX_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    results = fc3.apply(passing_df)
    actual = results["fc3_flag"].mean()
    expected = 0.11
    message = f"fc3 PASS actual is {actual} and expected is {expected}"
    assert actual == pytest.approx(expected), message
