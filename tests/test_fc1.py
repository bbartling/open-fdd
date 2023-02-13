# https://docs.pytest.org/en/6.2.x/skipping.html#id1

import os
import pytest


# dir_path = os.path.dirname(os.path.realpath(__file__))
# pytest_args = os.path.join(dir_path,'fc1.py')

'''
Run With
$ pytest
in this directory
'''

pytest_args = ['../fc1.py "Test Report"']
print(pytest_args)


def verify_if_file_exists():
    final_report_path = '../final_report/"Test Report".docx'
    final_report_existing = os.path.exists(final_report_path)

    # return boolean if report was generated
    return final_report_existing

def test_report_generated():
    assert generator()

def generator():
    pytest.main(pytest_args)
    return verify_if_file_exists()

