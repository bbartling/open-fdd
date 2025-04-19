#!/usr/bin/env python3
import os
import re

# Directory where fault condition files are located
directory = "/Users/acedrew/aceiot-projects/open-fdd/open_fdd/air_handling_unit/faults"

# Files to update (from fault_condition_two.py through fault_condition_sixteen.py)
files_to_update = [
    "fault_condition_two.py",
    "fault_condition_three.py",
    "fault_condition_four.py",
    "fault_condition_five.py",
    "fault_condition_six.py",
    "fault_condition_seven.py",
    "fault_condition_eight.py",
    "fault_condition_nine.py",
    "fault_condition_ten.py",
    "fault_condition_eleven.py",
    "fault_condition_twelve.py",
    "fault_condition_thirteen.py",
    "fault_condition_fourteen.py",
    "fault_condition_fifteen.py",
    "fault_condition_sixteen.py",
]


# Function to update a single file
def update_file(file_path):
    try:
        with open(file_path, "r") as file:
            lines = file.readlines()

        updated = False
        for i, line in enumerate(lines):
            # Check if this line contains a call to _apply_analog_checks and doesn't already have check_greater_than_one
            if "_apply_analog_checks" in line and "check_greater_than_one" not in line:
                if line.strip().endswith(")"):
                    # Remove the closing parenthesis
                    modified_line = (
                        line.rstrip(")\n") + ", check_greater_than_one=True)\n"
                    )
                    lines[i] = modified_line
                    updated = True

        if updated:
            with open(file_path, "w") as file:
                file.writelines(lines)
            print(f"Updated: {os.path.basename(file_path)}")
        else:
            print(f"No updates needed for: {os.path.basename(file_path)}")

    except Exception as e:
        print(f"Error processing {file_path}: {str(e)}")


# Process each file
for filename in files_to_update:
    file_path = os.path.join(directory, filename)
    if os.path.exists(file_path):
        update_file(file_path)
    else:
        print(f"File not found: {filename}")

print("Update complete.")
