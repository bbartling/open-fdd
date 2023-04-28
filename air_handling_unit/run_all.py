
import subprocess,sys

# tested on Windows 10 python 3.10.6
# py -3.10 run_all.py

runs = [
    'py ./fc1.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc1_report',
    'py ./fc1.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc1_report',
    'py ./fc1.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc1_report',
    'py ./fc2.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc2_report',
    'py ./fc2.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc2_report',
    'py ./fc2.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc2_report',
    'py ./fc3.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc3_report',
    'py ./fc3.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc3_report',
    'py ./fc3.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc3_report',
    'py ./fc4.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc4_report',
    'py ./fc4.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc4_report',
    'py ./fc4.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc4_report',
    'py ./fc5.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc5_report',
    'py ./fc5.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc5_report',
    'py ./fc5.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc5_report',
    'py ./fc7.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc7_report',
    'py ./fc7.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc7_report',
    'py ./fc7.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc7_report',
    'py ./fc8.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc8_report',
    'py ./fc8.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc8_report',
    'py ./fc8.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc8_report',
    'py ./fc9.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc9_report',
    'py ./fc9.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc9_report',
    'py ./fc9.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc9_report',
    'py ./fc10.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc10_report',
    'py ./fc10.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc10_report',
    'py ./fc10.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc10_report',
    'py ./fc11.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc11_report',
    'py ./fc11.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc11_report',
    'py ./fc11.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc11_report',
    'py ./fc12.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc12_report',
    'py ./fc12.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc12_report',
    'py ./fc12.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc12_report',
    'py ./fc13.py -i ./ahu_data/MZVAV-1.csv -o MZVAV-1_fc13_report',
    'py ./fc13.py -i ./ahu_data/MZVAV-2-1.csv -o MZVAV-2-1_fc13_report',
    'py ./fc13.py -i ./ahu_data/MZVAV-2-2.csv -o MZVAV-2-2_fc13_report',
]

EXIT_IF_ERROR = True

try:
    for run in runs:
        output = subprocess.check_output(run, shell=True)
        print(f"SUCCESS on {run}")
except ValueError as e:
    print(f"ERROR on {run} with: ",e)
    print(f"output is: ",output)
    if EXIT_IF_ERROR:
        sys.exit(0)



print("DONE DEAL ALL DONE!!!")
