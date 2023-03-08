"""
This module contains functions for generating and writing randomly generated data based on input specifications.

Functions:
- generate_data(input_specs, timestamp_range): Generates a Pandas DataFrame with randomly generated data based on the provided 
input specifications.
- write_csv(filename, header, data): Writes data to a CSV file.
- parse_config_file(config_file): Parses a configuration file and returns a list of InputSpec objects.
- get_timestamp_range(start_date, periods, freq): Returns a list of datetime objects with a specified frequency and number of periods.
"""
import argparse
import csv
import random
from datetime import datetime
from typing import Any, List, Union

import pandas as pd
import yaml

class InputSpec:
    """Represents a specification for a data input, including its name, range, and data type."""
    def __init__(self, name: str, low: Union[int, float], high: Union[int, float], data_type: type):
        self.name = name
        self.low = low
        self.high = high
        self.data_type = data_type



def generate_data(input_specs: List[InputSpec], timestamp_range: List[datetime]) -> pd.DataFrame:
    """
    Generate a Pandas DataFrame with randomly generated data based on the provided input specifications.

    Args:
        input_specs (List[InputSpec]): A list of InputSpec objects specifying the properties of each data column.
        timestamp_range (List[datetime]): A list of datetime objects representing the timestamps for each row.

    Returns:
        pd.DataFrame: A Pandas DataFrame containing the generated data.
    """
    data = []
    for timestamp in timestamp_range:
        row = {'datetime': timestamp}
        for spec in input_specs:
            sensor_name = spec.name
            sensor_low = spec.low
            sensor_high = spec.high
            sensor_type = spec.data_type

            if sensor_type == int:
                value = random.randint(sensor_low, sensor_high)
            else:
                value = round(random.uniform(sensor_low, sensor_high), 2)

            row[sensor_name] = value

        data.append(row)

    return pd.DataFrame(data)


def write_csv(filename: str, header: List[str], data: List[List[Any]]) -> None:
    """
    Write data to a CSV file.

    Args:
        filename (str): Name of the output file.
        header (List[str]): List of column names.
        data (List[List[Any]]): List of rows, where each row is a list of values.

    Returns:
        None
    """
    with open(filename, mode="w", newline="", encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for row in data:
            writer.writerow(row)

def parse_config_file(config_file: str) -> List[InputSpec]:
    """
    Parse configuration file and return a list of InputSpec objects.

    :param config_file: Path to the configuration file.
    :return: A list of InputSpec objects.
    """
    with open(config_file, "r", encoding='utf-8') as file_obj:
        config = yaml.safe_load(file_obj)

    input_specs = []
    for name, spec in config["inputs"].items():
        low = spec["low"]
        high = spec["high"]
        data_type = int if spec["data_type"] == "int" else float
        input_specs.append(InputSpec(name, low, high, data_type))

    return input_specs


def get_timestamp_range(start_date: datetime, periods: int, freq: str) -> List[datetime]:
    """
    Returns a list of datetime objects starting from `start_date` with a frequency of `freq` for `periods` number of periods.

    Parameters:
    start_date (datetime): The start date for the timestamp range.
    periods (int): The number of periods for the timestamp range.
    freq (str): The frequency of the timestamp range (1t=1 minute interval, 15m=15 minute interval).

    Returns:
    List[datetime]: A list of datetime objects with the specified frequency and number of periods.
    """
    date_range = pd.period_range(start=start_date, periods=periods, freq=freq)

    # timestamp range
    return [x.to_timestamp() for x in date_range]
