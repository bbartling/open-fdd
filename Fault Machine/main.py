
import pandas as pd
import argparse, math
from fault_machine import FaultMachine


parser = argparse.ArgumentParser(add_help=False)
args = parser.add_argument_group('Options')

args.add_argument('-h', '--help', action='help', help='Show this help message and exit.')

args.add_argument('-o', '--output', required=True, type=str,
                    help='Word File Output Name')
'''
FUTURE 
 * incorporate an arg for SI units 
 * °C on temp sensors
 * piping pressure sensor PSI conversion
 * air flow CFM conversion
 * AHU duct static pressure "WC

args.add_argument('--use-SI-units', default=False, action='store_true')
args.add_argument('--no-SI-units', dest='use-SI-units', action='store_false')
'''
args = parser.parse_args()


df = pd.read_csv(args.input,
    index_col='Date',
    parse_dates=True).rolling('5T').mean()

# pass in Pandas df
fm = FaultMachine(df)

# pull lever to run analysis
fm.run_analysis()