from faults import FaultConditionOne
import random
import pandas as pd
import pytest

TEST_DUCT_STATIC_COL = "duct_static"
TEST_DUCT_STATIC_SETPOINT_COL = "duct_static_setpoint"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
TEST_VFD_ERR_THRESHOLD = 0.05
TEST_VFD_SPEED_MAX = 0.7
TEST_DUCT_STATIC_ERR_THRESHOLD = 0.1


def fail_row() -> dict:
    data = {
        TEST_DUCT_STATIC_COL: 0.5,
        TEST_DUCT_STATIC_SETPOINT_COL: 1.1,
        TEST_SUPPLY_VFD_SPEED_COL: 0.99,
    }
    return data


def pass_row() -> dict:
    data = {
        TEST_DUCT_STATIC_COL: 1.5,
        TEST_DUCT_STATIC_SETPOINT_COL: 1.0,
        TEST_SUPPLY_VFD_SPEED_COL: 0.80,
    }
    return data


def generate_data(fail_portion: float, samples: int) -> pd.DataFrame:
    data = []
    for _ in range(samples):
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
    fc1 = FaultConditionOne(
        TEST_VFD_ERR_THRESHOLD,
        TEST_VFD_SPEED_MAX,
        TEST_DUCT_STATIC_ERR_THRESHOLD,
        TEST_DUCT_STATIC_COL,
        TEST_SUPPLY_VFD_SPEED_COL,
        TEST_DUCT_STATIC_SETPOINT_COL,
    )
    results = fc1.apply(failing_df)
    assert results["fc1_flag"].mean() > 0.4


def test_passing(passing_df):
    fc1 = FaultConditionOne(
        TEST_VFD_ERR_THRESHOLD,
        TEST_VFD_SPEED_MAX,
        TEST_DUCT_STATIC_ERR_THRESHOLD,
        TEST_DUCT_STATIC_COL,
        TEST_SUPPLY_VFD_SPEED_COL,
        TEST_DUCT_STATIC_SETPOINT_COL,
    )
    results = fc1.apply(passing_df)
    assert results["fc1_flag"].mean() < 0.2
