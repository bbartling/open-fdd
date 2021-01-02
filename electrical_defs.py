import time, glob, os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import ruptures as rpt
import calendar

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docxcompose.composer import Composer
from docx import Document as Document_compose
import os
import fnmatch, re
from datetime import datetime

import glob



#Change point algorith metric
metric = n_bkps=15
model = "l1"
min_size=1
jump=1

counter = 1

class Electrical_Defs():


    def clean_dataset(df):
        assert isinstance(df, pd.DataFrame), "df needs to be a pd.DataFrame"
        df.dropna(inplace=True)
        indices_to_keep = ~df.isin([np.nan, np.inf, -np.inf]).any(1)
        cleaner = (f'dataset has been cleaned')
        print(cleaner)
        return df[indices_to_keep].astype(np.float64)



    def adf_test(series,title=''):
        """
        Pass in a time series and an optional title, returns an ADF report
        """

        df = pd.DataFrame(series)
        starting = (f'Augmented Dickey-Fuller Test: {title}')
        print(starting)
        result = adfuller(df.dropna(),autolag='AIC') # .dropna() handles differenced data

        labels = ['ADF test statistic','p-value','# lags used','# observations']
        out = pd.Series(result[0:4],index=labels)

        for key,val in result[4].items():
            out[f'critical value ({key})']=val

        info = out.to_string()
        model_info = f"model info: {info}"
        print(model_info)      # .to_string() removes the line "dtype: float64"

        if result[1] <= 0.05:
            print("Strong evidence against the null hypothesis")
            print(f"Reject the null hypothesis")
            print(f"Data has no unit root and is stationary")

        else:
            print(f"Weak evidence against the null hypothesis")
            print(f"Fail to reject the null hypothesis")
            print(f"Data has a unit root and is non-stationary")



    def changPointDf(df):

        arr = np.array(df.kW)
        # change point detection
        algo = rpt.Dynp(model=model, min_size=min_size, jump=jump).fit(arr)

        try:
            my_bkps = algo.predict(metric)

            # getting the timestamps of the change points
            bkps_timestamps = df.iloc[[0] + my_bkps[:-1] +[-1]].index

            # computing the durations between change points
            durations = (bkps_timestamps[1:] - bkps_timestamps[:-1])

            #hours calc
            d = durations.seconds/60/60
            d_f = pd.DataFrame(d)
            df2 = d_f.T

            # getting kW Avg of the change points
            bkps_timestamps_kW = df.iloc[[0] + my_bkps[:-1] +[-1]]

            kW1diff = bkps_timestamps_kW.kW.iloc[1] - bkps_timestamps_kW.kW.iloc[0]
            kW2diff = bkps_timestamps_kW.kW.iloc[2] - bkps_timestamps_kW.kW.iloc[1]
            kW3diff = bkps_timestamps_kW.kW.iloc[3] - bkps_timestamps_kW.kW.iloc[2]
            kW4diff = bkps_timestamps_kW.kW.iloc[4] - bkps_timestamps_kW.kW.iloc[3]
            kW5diff = bkps_timestamps_kW.kW.iloc[5] - bkps_timestamps_kW.kW.iloc[4]
            kW6diff = bkps_timestamps_kW.kW.iloc[6] - bkps_timestamps_kW.kW.iloc[5]
            kW7diff = bkps_timestamps_kW.kW.iloc[7] - bkps_timestamps_kW.kW.iloc[6]
            kW8diff = bkps_timestamps_kW.kW.iloc[8] - bkps_timestamps_kW.kW.iloc[7]
            kW9diff = bkps_timestamps_kW.kW.iloc[9] - bkps_timestamps_kW.kW.iloc[8]
            kW10diff = bkps_timestamps_kW.kW.iloc[10] - bkps_timestamps_kW.kW.iloc[9]
            kW11diff = bkps_timestamps_kW.kW.iloc[11] - bkps_timestamps_kW.kW.iloc[10]
            kW12diff = bkps_timestamps_kW.kW.iloc[12] - bkps_timestamps_kW.kW.iloc[11]
            kW13diff = bkps_timestamps_kW.kW.iloc[13] - bkps_timestamps_kW.kW.iloc[12]
            kW14diff = bkps_timestamps_kW.kW.iloc[14] - bkps_timestamps_kW.kW.iloc[13]
            kW15diff = bkps_timestamps_kW.kW.iloc[15] - bkps_timestamps_kW.kW.iloc[14]
            kW16diff = bkps_timestamps_kW.kW.iloc[16] - bkps_timestamps_kW.kW.iloc[15]

            kW1Hrs = d_f.values[0][0]
            kW2Hrs = d_f.values[1][0]
            kW3Hrs = d_f.values[2][0]
            kW4Hrs = d_f.values[3][0]
            kW5Hrs = d_f.values[4][0]
            kW6Hrs = d_f.values[5][0]
            kW7Hrs = d_f.values[6][0]
            kW8Hrs = d_f.values[7][0]
            kW9Hrs = d_f.values[8][0]
            kW10Hrs = d_f.values[9][0]
            kW11Hrs = d_f.values[10][0]
            kW12Hrs = d_f.values[11][0]
            kW13Hrs = d_f.values[12][0]
            kW14Hrs = d_f.values[13][0]
            kW15Hrs = d_f.values[14][0]
            kW16Hrs = d_f.values[15][0]

            alldata = [
            kW1diff, kW1Hrs,
            kW2diff, kW2Hrs,
            kW3diff, kW3Hrs,
            kW4diff, kW4Hrs,
            kW5diff, kW5Hrs,
            kW6diff, kW6Hrs,
            kW7diff, kW7Hrs,
            kW8diff, kW8Hrs,
            kW9diff, kW9Hrs,
            kW10diff, kW10Hrs,
            kW11diff, kW11Hrs,
            kW12diff, kW12Hrs,
            kW13diff, kW13Hrs,
            kW14diff, kW14Hrs,
            kW15diff, kW15Hrs,
            kW16diff, kW16Hrs
                         ]
            return alldata

        except:
            d = df.index.day[0]
            m = df.index.month_name()[0]

            print(f'oh no!! {m} {d}, unable to compile change point algorithm on this day...')

            data = [0, 0, 0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0,
                    0,0
                    ]

            return data


    def changPoint2(df, dayNum, yTickMax, stdy):
        global counter

        df = df.loc[df.index.day.isin([dayNum])]
        arr = np.array(df.kW)


        algo = rpt.Dynp(model=model, min_size=min_size, jump=jump).fit(arr)
        my_bkps = algo.predict(metric)

        # getting the timestamps of the change points
        bkps_timestamps = df.iloc[[0] + my_bkps[:-1] +[-1]].index
        # computing the durations between change points
        durations = (bkps_timestamps[1:] - bkps_timestamps[:-1])
        #hours calc
        d = durations.seconds/60/60
        d_f = pd.DataFrame(d)
        df2 = d_f.T

        # getting kW Avg of the change points
        bkps_timestamps_kW = df.iloc[[0] + my_bkps[:-1] +[-1]]


        kW1diff = bkps_timestamps_kW.kW.iloc[1] - bkps_timestamps_kW.kW.iloc[0]
        kW2diff = bkps_timestamps_kW.kW.iloc[2] - bkps_timestamps_kW.kW.iloc[1]
        kW3diff = bkps_timestamps_kW.kW.iloc[3] - bkps_timestamps_kW.kW.iloc[2]
        kW4diff = bkps_timestamps_kW.kW.iloc[4] - bkps_timestamps_kW.kW.iloc[3]
        kW5diff = bkps_timestamps_kW.kW.iloc[5] - bkps_timestamps_kW.kW.iloc[4]
        kW6diff = bkps_timestamps_kW.kW.iloc[6] - bkps_timestamps_kW.kW.iloc[5]
        kW7diff = bkps_timestamps_kW.kW.iloc[7] - bkps_timestamps_kW.kW.iloc[6]
        kW8diff = bkps_timestamps_kW.kW.iloc[8] - bkps_timestamps_kW.kW.iloc[7]
        kW9diff = bkps_timestamps_kW.kW.iloc[9] - bkps_timestamps_kW.kW.iloc[8]
        kW10diff = bkps_timestamps_kW.kW.iloc[10] - bkps_timestamps_kW.kW.iloc[9]
        kW11diff = bkps_timestamps_kW.kW.iloc[11] - bkps_timestamps_kW.kW.iloc[10]
        kW12diff = bkps_timestamps_kW.kW.iloc[12] - bkps_timestamps_kW.kW.iloc[11]
        kW13diff = bkps_timestamps_kW.kW.iloc[13] - bkps_timestamps_kW.kW.iloc[12]
        kW14diff = bkps_timestamps_kW.kW.iloc[14] - bkps_timestamps_kW.kW.iloc[13]
        kW15diff = bkps_timestamps_kW.kW.iloc[15] - bkps_timestamps_kW.kW.iloc[14]
        kW16diff = bkps_timestamps_kW.kW.iloc[16] - bkps_timestamps_kW.kW.iloc[15]

        kW1Hrs = d_f.values[0][0]
        kW2Hrs = d_f.values[1][0]
        kW3Hrs = d_f.values[2][0]
        kW4Hrs = d_f.values[3][0]
        kW5Hrs = d_f.values[4][0]
        kW6Hrs = d_f.values[5][0]
        kW7Hrs = d_f.values[6][0]
        kW8Hrs = d_f.values[7][0]
        kW9Hrs = d_f.values[8][0]
        kW10Hrs = d_f.values[9][0]
        kW11Hrs = d_f.values[10][0]
        kW12Hrs = d_f.values[11][0]
        kW13Hrs = d_f.values[12][0]
        kW14Hrs = d_f.values[13][0]
        kW15Hrs = d_f.values[14][0]
        kW16Hrs = d_f.values[15][0]

        # show results
        rpt.show.display(arr, my_bkps, figsize=(17, 6))
        #plot metrics

        one = f'{round(kW1Hrs,1)} hrs'
        ONE = f'{int(kW1diff)} kW'

        two = f'{round(kW2Hrs,1)} hrs'
        TWO = f'{int(kW2diff)} kW'

        three = f'{round(kW3Hrs,1)} hrs'
        THREE = f'{int(kW3diff)} kW'

        four = f'{round(kW4Hrs,1)} hrs'
        FOUR = f'{int(kW4diff)} kW'

        five = f'{round(kW5Hrs,1)} hrs'
        FIVE = f'{int(kW5diff)} kW'

        six = f'{round(kW6Hrs,1)} hrs'
        SIX = f'{int(kW6diff)} kW'

        seven = f'{round(kW7Hrs,1)} hrs'
        SEVEN = f'{int(kW7diff)} kW'

        eight = f'{round(kW8Hrs,1)} hrs'
        EIGHT = f'{int(kW8diff)} kW'

        nine = f'{round(kW9Hrs,1)} hrs'
        NINE = f'{int(kW9diff)} kW'

        ten = f'{round(kW10Hrs,1)} hrs'
        TEN = f'{int(kW10diff)} kW'

        eleven = f'{round(kW11Hrs,1)} hrs'
        ELEVEN = f'{int(kW11diff)} kW'

        twelve = f'{round(kW12Hrs,1)} hrs'
        TWELVE = f'{int(kW12diff)} kW'

        thirt = f'{round(kW9Hrs,1)} hrs'
        THIRT = f'{int(kW13diff)} kW'

        fourt = f'{round(kW10Hrs,1)} hrs'
        FOURT = f'{int(kW14diff)} kW'

        fift = f'{round(kW11Hrs,1)} hrs'
        FIFT = f'{int(kW15diff)} kW'

        sixt = f'{round(kW12Hrs,1)} hrs'
        SIXT = f'{int(kW16diff)} kW'

        d = df.index.day_name()[0]
        m = df.index.month_name()[0]

        title = f'Change Point Detection: Dynamic Programming Method {d} {m} {dayNum}'
        #plt.suptitle(title)
        plt.text(0, yTickMax, title)

        plt.text(0, 0, one)
        plt.text(0, stdy, ONE)
        plt.text(my_bkps[0], 0, two)
        plt.text(my_bkps[0], stdy, TWO)
        plt.text(my_bkps[1], 0, three)
        plt.text(my_bkps[1], stdy, THREE)
        plt.text(my_bkps[2], 0, four)
        plt.text(my_bkps[2], stdy, FOUR)
        plt.text(my_bkps[3], 0, five)
        plt.text(my_bkps[3], stdy, FIVE)
        plt.text(my_bkps[4], 0, six)
        plt.text(my_bkps[4], stdy, SIX)
        plt.text(my_bkps[5], 0, seven)
        plt.text(my_bkps[5], stdy, SEVEN)
        plt.text(my_bkps[6], 0, eight)
        plt.text(my_bkps[6], stdy, EIGHT)
        plt.text(my_bkps[7], 0, nine)
        plt.text(my_bkps[7], stdy, NINE)
        plt.text(my_bkps[8], 0, ten)
        plt.text(my_bkps[8], stdy, TEN)
        plt.text(my_bkps[9], 0, eleven)
        plt.text(my_bkps[9], stdy, ELEVEN)
        plt.text(my_bkps[10], 0, twelve)
        plt.text(my_bkps[10], stdy, TWELVE)
        plt.text(my_bkps[11], 0, thirt)
        plt.text(my_bkps[11], stdy, THIRT)
        plt.text(my_bkps[12], 0, fourt)
        plt.text(my_bkps[12], stdy, FOURT)
        plt.text(my_bkps[13], 0, fift)
        plt.text(my_bkps[13], stdy, FIFT)
        plt.text(my_bkps[14], 0, sixt)
        plt.text(my_bkps[14], stdy, SIXT)

        plt.ylim(0, yTickMax)
        #plt.show()
        #fig = plt.figure()

        plt.savefig('./static_main/' + f'algSanChck_{counter}' + '.png')
        counter += 1
