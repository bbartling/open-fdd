"""
This file contains a script for generating and writing randomly generated data to a CSV file based on a configuration file.

To run this script, you must provide the following arguments:

config_file: Path to the configuration file.
output_filename: Name of the output CSV file.
Optional arguments:

start_date: The start date (YYYY-MM-DD) for data generation. Defaults to today.
periods: The number of periods for data generation. Defaults to approximately one month of data in one minute intervals.
freq: The frequency of data generation. Must be either "1t" (1 minute intervals) or "15m" (15 minute intervals). Defaults to "1t".
Example usage:
python generate_data.py config.yaml output.csv --start_date 2022-01-01 --periods 10080 --freq 15m

This will generate a CSV file named "output.csv" with data based on the configuration file "config.yaml" starting from January 1, 2022 
with 10080 periods (15 minute intervals).
"""
import argparse
import os
import sys

from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# pylint: disable=wrong-import-position
from scripts import get_timestamp_range, generate_data, write_csv, parse_config_file


def main():
    """
    Parse the command line arguments, generate data based on the configuration file, and write it to a CSV file.

    Required arguments:
    - config_file: Path to the configuration file.
    - output_filename: Name of the output CSV file.

    Optional arguments:
    - start_date: The start date (YYYY-MM-DD) for data generation. Defaults to today.
    - periods: The number of periods for data generation. Defaults to approximately one month of data in one minute intervals.
    - freq: The frequency of data generation. Must be either "1t" (1 minute intervals) or "15m" (15 minute intervals). Defaults to "1t".
    """
    parser = argparse.ArgumentParser(description="Generate data based on configuration file.")
    parser.add_argument("config_file", type=str, help="Path to configuration file")
    parser.add_argument(
        "--start_date",
        type=str,
        help="Start date (YYYY-MM-DD) for data generation",
    )
    parser.add_argument(
        "--periods",
        type=int,
        help="Number of periods for data generation (default is approximately 1 month)",
    )
    parser.add_argument(
        "--freq",
        type=str,
        choices=["1t", "15m"],
        default="1t",
        help="Frequency of data generation (1m=1 minute interval, 15m=15 minute interval)",
    )
    parser.add_argument("output_filename", type=str, help="Name of output file")

    args = parser.parse_args()

    # Parse configuration file
    input_specs = parse_config_file(args.config_file)

    # Get start date
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d') if args.start_date else datetime.today()

    # Get number of periods
    periods = args.periods if args.periods else int(30 * 24 * 60)  # approximately one month of data in one minute intervals

    # Get freq
    freq = args.freq

    timestamp_range = get_timestamp_range(start_date, periods, freq)

    data = generate_data(input_specs, timestamp_range)

    # Get output filename
    output_filename = args.output_filename
    fieldnames = ['datetime'] + [spec.name for spec in input_specs]
    write_csv(output_filename, fieldnames, data.values.tolist())


if __name__ == '__main__':
    main()
