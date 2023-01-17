import pandas as pd
import datetime
import random
import matplotlib.pyplot as plt

# one month on 15 minute intervals
one_month = 96*31

# range of dates
date_range = pd.period_range(
    start=datetime.datetime.today(), periods=one_month, freq='15T')

# timestamp range
timestamp_range = [x.to_timestamp() for x in date_range]

# all device signal outputs are in %
SAT_LOW = 60
SAT_HIGH = 90
sat_init = random.randint(SAT_LOW, SAT_HIGH)

# all device signal outputs are in %
SAT_SP_LOW = 70
SAT_SP_HIGH = 80
sat_sp_init = random.randint(SAT_SP_LOW, SAT_SP_HIGH)

HTG_LOW = 70
HTG_HIGH = 100
htg_init = random.randint(HTG_LOW, HTG_HIGH)


def data_generator(sensor, TEMP_LOW, TEMP_HIGH, temp_init):

    final_rand_data = []
    temp_lv = None
    global timestamp_range

    # iterating through timestamp range
    for i in range(len(timestamp_range)):
        stamp_and_temp = {}
        if temp_lv == None:
            _temp = temp_init
        else:
            # generate rand float between 0 and 1
            rander = random.random()
            if rander > .5:
                rander = 1
            else:
                rander = -1
            _temp = _temp + rander
        if _temp > TEMP_HIGH:
            _temp -= 1
        if _temp < TEMP_LOW:
            _temp += 1
        stamp_and_temp['Date'] = timestamp_range[i]
        stamp_and_temp[str(sensor)] = _temp
        final_rand_data.append(stamp_and_temp)
        temp_lv = _temp
    return final_rand_data



sat_final = data_generator(
    'sat', SAT_LOW, SAT_HIGH, sat_init)
sat_sp_final = data_generator(
    'satsp', SAT_SP_LOW, SAT_SP_HIGH, sat_sp_init)
htg_final = data_generator(
    'htg', HTG_LOW, HTG_HIGH, htg_init)


df_1 = pd.DataFrame(sat_final)
df_1 = df_1.set_index('Date')
print(df_1)

df_2 = pd.DataFrame(sat_sp_final)
df_2 = df_2.set_index('Date')
print(df_2)

df_3 = pd.DataFrame(htg_final)
df_3 = df_3.set_index('Date')

df_12 = df_1.join(df_2)
df_final = df_12.join(df_3)
print(df_final)

df_final.plot()
plt.show()

df_final.to_csv('fc7_fake_data3.csv')
print('DONE!!!')
