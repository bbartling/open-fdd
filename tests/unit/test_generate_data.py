import unittest
import os
import datetime
from io import StringIO
import tempfile

# import sys
# sys.path.append('../../scripts')
# from generated_data import InputSpec
# from scripts import InputSpec
# from scripts import generate_data

from scripts import InputSpec, get_timestamp_range, generate_data, write_csv, parse_config_file



class TestDataGenerator(unittest.TestCase):
    def test_InputSpec(self):
        input_spec = InputSpec(name="temperature", low=0, high=100, data_type=int)
        self.assertEqual(input_spec.name, "temperature")
        self.assertEqual(input_spec.low, 0)
        self.assertEqual(input_spec.high, 100)
        self.assertEqual(input_spec.data_type, int)

    def test_generate_data(self):
        input_specs = [InputSpec(name="temperature", low=0, high=100, data_type=int),
                    InputSpec(name="humidity", low=0, high=100, data_type=int)]

        start_date = datetime.datetime.now()
        periods = 5
        freq = "1t"
        timestamp_range = get_timestamp_range(start_date, periods, freq)

        data = generate_data(input_specs, timestamp_range)

        self.assertEqual(len(data), periods)
        self.assertListEqual(list(data.columns), ['datetime', 'temperature', 'humidity'])

    def test_write_csv(self):
        header = ['name', 'age', 'city']
        data = [['Alice', 25, 'New York'], ['Bob', 30, 'Los Angeles']]

        # Use a temporary file for the test output
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            write_csv(temp_file.name, header, data)

            with open(temp_file.name, mode="r", encoding='utf-8') as file:
                content = file.read()

        expected_output = 'name,age,city\nAlice,25,New York\nBob,30,Los Angeles\n'
        self.assertEqual(content, expected_output)

    def test_parse_config_file(self):
        fc1_config = "ahu_data/configs/fc1.yaml"
        input_specs = parse_config_file(fc1_config)

        self.assertEqual(len(input_specs), 2)
        self.assertListEqual([spec.name for spec in input_specs], ['supply_vfd_speed', 'duct_static'])
        self.assertListEqual([spec.low for spec in input_specs], [10, 0.01])
        self.assertListEqual([spec.high for spec in input_specs], [100, 2])
        self.assertListEqual([spec.data_type for spec in input_specs], [int, float])

    def test_get_timestamp_range(self):
        start_date = datetime.datetime(2022, 1, 1)
        periods = 5
        freq = "1t"

        timestamp_range = get_timestamp_range(start_date, periods, freq)

        self.assertEqual(len(timestamp_range), periods)
        self.assertListEqual([str(timestamp) for timestamp in timestamp_range],
                            ['2022-01-01 00:00:00', '2022-01-01 00:01:00', '2022-01-01 00:02:00',
                            '2022-01-01 00:03:00', '2022-01-01 00:04:00'])
# if name == 'main':
# unittest.main()