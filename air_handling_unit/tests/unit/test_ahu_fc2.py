from faults import FaultConditionTwo
import random
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest -rP

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


# mix air temp lower than out temp
def fail_row() -> dict:
    data = {
        TEST_MIX_TEMP_COL : 40.,
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
    fc2 = FaultConditionTwo(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_RETURN_DEGF_ERR_THRES,
    TEST_OUTDOOR_DEGF_ERR_THRES,
    TEST_MIX_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    results = fc2.apply(failing_df)
    print("FC2 FAIL ",results)
    flag_mean = results["fc2_flag"].mean()
    print("FC2 FAIL flag_mean",flag_mean)
    flag_describe = results["fc2_flag"].describe()
    print("FC2 FAIL describe",flag_describe)
    assert flag_mean >= 0.89


def test_passing(passing_df):
    fc1 = FaultConditionTwo(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_RETURN_DEGF_ERR_THRES,
    TEST_OUTDOOR_DEGF_ERR_THRES,
    TEST_MIX_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    results = fc1.apply(passing_df)
    print("FC2 PASSING ",results)
    flag_mean = results["fc2_flag"].mean()
    print("FC2 PASSING flag_mean",flag_mean)
    flag_describe = results["fc2_flag"].describe()
    print("FC2 PASSING describe",flag_describe)
    assert flag_mean <= 0.11