import operator
import time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from docx import Document
from docx.shared import Inches

import argparse

# python 3.10 on Windows 10
# py .\fc4.py -i ./ahu_data/hvac_random_fake_data/fc4_fake_data1.csv -o fake1_ahu_fc4_report

parser = argparse.ArgumentParser(add_help=False)
args = parser.add_argument_group('Options')

args.add_argument('-h', '--help', action='help', help='Show this help message and exit.')
args.add_argument('-i', '--input', required=True, type=str,
                    help='CSV File Input')
args.add_argument('-o', '--output', required=True, type=str,
                    help='Word File Output Name')
'''
args.add_argument('--use-flask', default=False, action='store_true')
args.add_argument('--no-flask', dest='use-flask', action='store_false')
'''
args = parser.parse_args()

# required params taken from the screenshot above
AHU_MIN_OA = 20
DELTA_OS_MAX = 7.


'''
cooling_sig = pd.read_csv(
    './ahu_data/CLG-O.csv',
    index_col='Date',
    parse_dates=True).fillna(method='ffill').fillna(method='bfill').dropna()
cooling_sig = cooling_sig.rolling('5T').mean()

heating_sig = pd.read_csv(
    './ahu_data/HTG-O.csv',
    index_col='Date',
    parse_dates=True).fillna(method='ffill').fillna(method='bfill').dropna()
heating_sig = heating_sig.rolling('5T').mean()

economizer_sig = pd.read_csv(
    './ahu_data/DPR-O.csv',
    index_col='Date',
    parse_dates=True).fillna(method='ffill').fillna(method='bfill').dropna()
economizer_sig = economizer_sig.rolling('5T').mean()

clg_htg = cooling_sig.join(heating_sig)
df = economizer_sig.join(clg_htg)
'''


df = pd.read_csv(args.input,
    index_col='Date',
    parse_dates=True).rolling('5T').mean()

print(df)
df_copy = df.copy()

df_copy.plot(figsize=(25, 8),
         title='AHU Heating, Cooling, and OA Damper Signals')
plt.savefig('./static/ahu_fc4_signals.png')

# make an entire column out of these params in the Pandas Dataframe
df['delta_os_max'] = AHU_MIN_OA
df['ahu_min_oa'] = DELTA_OS_MAX

start = df.head(1).index.date
print('Dataset start: ', start)

end = df.tail(1).index.date
print('Dataset end: ', end)
print('COLUMNS: ', print(df.columns))


df['heating_mode'] = df['heating_sig'].gt(0.)
df['econ_mode'] = df['economizer_sig'].gt(df['ahu_min_oa']) & df['cooling_sig'].eq(0.)
df['econplusmech_cooling_mode'] = df['economizer_sig'].gt(df['ahu_min_oa']) & df['cooling_sig'].gt(0.)
df['mech_cooling_mode'] = df['economizer_sig'].eq(df['ahu_min_oa']) & df['cooling_sig'].gt(0.)

df = df[['heating_mode','econ_mode','econplusmech_cooling_mode','mech_cooling_mode']]

df = df.astype(int)

# calc changes per hour for modes
# https://stackoverflow.com/questions/69979832/pandas-consecutive-boolean-event-rollup-time-series
df = df.resample('H').apply(lambda x: (x.eq(1) & x.shift().ne(1)).sum())

df_debug =  df.copy()

df['fc4_flag'] = df[df.columns].gt(DELTA_OS_MAX).any(1)
df = df.astype(int)

print('df.fc4_flag.describe')
print(df.fc4_flag.describe())

flag4_max_val = df.fc4_flag.max()
print('df.fc4_flag.max = ',flag4_max_val)

df.plot(figsize=(25, 8), subplots=True,
         title='AHU Operating States')
plt.savefig('./static/ahu_fc4_oper_states.png')


print("Starting ahu fc4 docx report")
document = Document()
document.add_heading('Fault Condition Four Report', 0)

p = document.add_paragraph(
    'Fault condition four of ASHRAE Guideline 36 is related to flagging control programming that is hunting causing excessive oscilating between heating, economizing, economizing plus mechanical cooling, and mechanical cooling operating states. Fault condition four equation as defined by ASHRAE:')
document.add_picture('./images/fc4_definition.png', width=Inches(6))

document.add_heading('Heating, Cooling, and OA Damper Signal Plot', level=2)
document.add_picture('./static/ahu_fc4_signals.png', width=Inches(6))

document.add_heading('Calculated Operating States Plot', level=2)
document.add_picture('./static/ahu_fc4_oper_states.png', width=Inches(6))

document.add_heading('Dataset Statistics', level=2)

# calculate dataset statistics
df["timedelta_alldata"] = df.index.to_series().diff()
seconds_alldata = df.timedelta_alldata.sum().seconds
days_alldata = df.timedelta_alldata.sum().days
hours_alldata = round(seconds_alldata/3600,2)
minutes_alldata = round((seconds_alldata/60) % 60,2)
total_hours_calc = days_alldata * 24.0 + hours_alldata

# calculate time statistics while in different modes
df["timedelta_heating_mode"] = df.index.to_series().diff().where(df["heating_mode"] == 1)
seconds_htg_mode = df.timedelta_heating_mode.sum().seconds
hours_htg_mode = round(seconds_htg_mode/3600,2)
percent_true_heating_mode = round(df.heating_mode.mean() * 100, 2)

df["timedelta_econ_mode"] = df.index.to_series().diff().where(df["econ_mode"] == 1)
seconds_econ_mode = df.timedelta_econ_mode.sum().seconds
hours_econ_mode = round(seconds_econ_mode/3600,2)
percent_true_econ_mode = round(df.econ_mode.mean() * 100, 2)

df["timedelta_econplusmech_cooling_mode"] = df.index.to_series().diff().where(df["econplusmech_cooling_mode"] == 1)
seconds_econplusmech_cooling_mode = df.timedelta_econplusmech_cooling_mode.sum().seconds
hours_econplusmech_cooling = round(seconds_econplusmech_cooling_mode/3600,2)
percent_true_econplusmech_cooling_mode = round(df.econplusmech_cooling_mode.mean() * 100, 2)

df["timedelta_mech_cooling_mode"] = df.index.to_series().diff().where(df["mech_cooling_mode"] == 1)
seconds_mech_cooling_mode = df.timedelta_mech_cooling_mode.sum().seconds
hours_mech_cooling_mode = round(seconds_mech_cooling_mode/3600,2)
percent_true_mech_cooling_mode = round(df.mech_cooling_mode.mean() * 100, 2)

# add calcs to word doc
paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time calculated in dataset: {df.timedelta_alldata.sum()}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time in hours calculated in dataset: {total_hours_calc}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time in hours while AHU is in a heating mode: {hours_htg_mode}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total percent time in while AHU is in a heating mode: {percent_true_heating_mode}%')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time in hours while AHU is in a economizing mode: {hours_econ_mode}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total percent time in while AHU is in a economizing mode: {percent_true_econ_mode}%')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time in hours while AHU is in a economizing plus mechanical cooling mode: {hours_econplusmech_cooling}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total percent time in while AHU is in a economizing plus mechanical cooling mode: {percent_true_econplusmech_cooling_mode}%')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total time in hours while AHU is in a mechanical cooling mode: {hours_mech_cooling_mode}')

paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(
    f'Total percent time in while AHU is in a mechanical cooling mode: {hours_mech_cooling_mode}%')

# skip calculating statistics if there is no fault 4's
# Pandas calcs alot of NaNs and errors out
if flag4_max_val != 0:
    
    # fc4 stats for histogram plot
    df["timedelta_fddflag_fc4"] = df.index.to_series().diff().where(df["fc4_flag"] == 1)
    percent_true_fc4 = round(df.fc4_flag.mean() * 100, 2)

    percent_false_fc4 = round((100 - percent_true_fc4), 2)
    df['hour_of_the_day_fc4'] = df.index.hour.where(df["fc4_flag"] == 1)

    # flag_true_fc4
    flag_true_heating_mode = round(
        df.heating_mode.where(df["fc4_flag"] == 1).mean(), 2)
    flag_true_econ_mode = round(
        df.econ_mode.where(df["fc4_flag"] == 1).mean(), 2)
    flag_true_econplusmech_cooling_mode = round(
        df.econplusmech_cooling_mode.where(df["fc4_flag"] == 1).mean(), 2)
    flag_true_mech_cooling_mode = round(
        df.mech_cooling_mode.where(df["fc4_flag"] == 1).mean(), 2)


    # make hist plots
    df['hour_of_the_day'] = df.index.hour.where(df["fc4_flag"] == 1)

    print('DF HOUR OF DAY')
    print(df.hour_of_the_day)
    print(df.hour_of_the_day.describe())

    # make hist plots fc3
    fig, ax = plt.subplots(tight_layout=True, figsize=(25,8))
    ax.hist(df.hour_of_the_day)
    ax.set_xlabel('24 Hour Number in Day')
    ax.set_ylabel('Frequency')
    ax.set_title(f'Hour-Of-Day When Fault Flag 4 is TRUE')
    fig.savefig('./static/ahu_fc4_histogram.png')

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Total time for when fault flag 4 is True: {df.timedelta_fddflag_fc4.sum()}')

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Percent of time in the dataset when the fault flag 4 is True: {percent_true_fc4}%')

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Percent of time in the dataset when fault flag 4 is False: {percent_false_fc4}%')

    paragraph = document.add_paragraph()
    # ADD HIST Plots
    document.add_heading('Time-of-day Histogram Plots', level=2)
    document.add_picture('./static/ahu_fc4_histogram.png', width=Inches(6))

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Control system in a heating mode while fault condition 4 is True: {flag_true_heating_mode} °F')
    paragraph = document.add_paragraph()

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Control system in a free economizer mode while fault condition 4 is True: {flag_true_econ_mode} °F')
    paragraph = document.add_paragraph()

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Control system in a economizer and mechanical cooling mode while fault condition 4 is True: {flag_true_econplusmech_cooling_mode} °F')
    paragraph = document.add_paragraph()

    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'Control system in a mechanical cooling mode while fault condition 4 is True: {flag_true_mech_cooling_mode} °F')
    paragraph = document.add_paragraph()


else:
    paragraph = document.add_paragraph()
    paragraph.style = 'List Bullet'
    paragraph.add_run(
        f'No fault condition 4 calcualted in the dataset')
    paragraph = document.add_paragraph()



# ADD in Summary Statistics
document.add_heading('Heating Signal Statistics', level=2)
paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(str(df_copy.heating_sig.describe()))

# ADD in Summary Statistics
document.add_heading('Cooling Signal Statistics', level=2)
paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(str(df_copy.cooling_sig.describe()))

# ADD in Summary Statistics
document.add_heading('Economizer Free Cooling Statistics', level=2)
paragraph = document.add_paragraph()
paragraph.style = 'List Bullet'
paragraph.add_run(str(df_copy.economizer_sig.describe()))


paragraph = document.add_paragraph()
run = paragraph.add_run(f'Report generated: {time.ctime()}')
run.style = 'Emphasis'

document.save(f'./final_report/{args.output}.docx')
print('All Done WITH: ',args.output)
