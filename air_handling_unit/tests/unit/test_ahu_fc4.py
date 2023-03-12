from faults import FaultConditionFour
import random
import pandas as pd
import pytest
import datetime

'''
to see print statements in pytest run with
$ pytest -rP
$ pytest tests/unit/test_ahu_fc4.py -rP

random seed set every time random.random()
is called so the results to be exact same
every time for the flag mean col output.

Future compare to ML FDD Vs rule based FDD
'''


DELTA_OS_MAX = 7
AHU_MIN_OA = .20
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "fan_vfd_speed_col"

DATASET_ROWS = 1000

def generate_timestamp() -> pd.Series:
    df = pd.DataFrame()
    date_range = pd.period_range(
        start=datetime.datetime.today(), periods=DATASET_ROWS, freq='1T')
    df['Date'] = [x.to_timestamp() for x in date_range]
    return df['Date']

# mix air temp higher than out temp
def fail_row() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL : .6,
        TEST_HEATING_COIL_SIG_COL : 0,
        TEST_COOLING_COIL_SIG_COL : .6,
        TEST_SUPPLY_VFD_SPEED_COL : .8,
    }
    return data


def pass_row() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL : 0,
        TEST_HEATING_COIL_SIG_COL : 0,
        TEST_COOLING_COIL_SIG_COL : .6,
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
    return generate_data(0.9, DATASET_ROWS)


@pytest.fixture
def passing_df() -> pd.DataFrame:
    return generate_data(0.5, DATASET_ROWS)


def test_failing(failing_df):
    fc4 = FaultConditionFour(
    DELTA_OS_MAX,
    AHU_MIN_OA,
    TEST_MIX_AIR_DAMPER_COL,
    TEST_HEATING_COIL_SIG_COL,
    TEST_COOLING_COIL_SIG_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    
    failing_df = failing_df.set_index(generate_timestamp())
    results = fc4.apply(failing_df)
    actual = results["fc4_flag"].sum()
    expected = 3.
    message = f"fc4 FAIL actual is {actual} and expected is {expected}"
    assert actual == pytest.approx(expected), message



def test_passing(passing_df):
    fc4 = FaultConditionFour(
    DELTA_OS_MAX,
    AHU_MIN_OA,
    TEST_MIX_AIR_DAMPER_COL,
    TEST_HEATING_COIL_SIG_COL,
    TEST_COOLING_COIL_SIG_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    )
    
    passing_df = passing_df.set_index(generate_timestamp())
    results = fc4.apply(passing_df)
    actual = results["fc4_flag"].sum()
    expected = 16.
    message = f"fc4 PASS actual is {actual} and expected is {expected}"
    assert actual == pytest.approx(expected), message

