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

MIX_TEMP_LOW = 30
MIX_TEMP_HIGH = 80
mix_temp_init = random.randint(MIX_TEMP_LOW, MIX_TEMP_HIGH)

RETURN_TEMP_LOW = 30
RETURN_TEMP_HIGH = 80
return_temp_init = random.randint(RETURN_TEMP_LOW, RETURN_TEMP_HIGH)

OUTSIDE_TEMP_LOW = -15
OUTSIDE_TEMP_HIGH = 110
outside_temp_init = random.randint(OUTSIDE_TEMP_LOW, OUTSIDE_TEMP_HIGH)


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


mixing_temp_final = data_generator(
    'mat', MIX_TEMP_LOW, MIX_TEMP_HIGH, mix_temp_init)
return_temp_final = data_generator(
    'rat', RETURN_TEMP_LOW, RETURN_TEMP_HIGH, return_temp_init)
outside_temp_final = data_generator(
    'oat', OUTSIDE_TEMP_LOW, OUTSIDE_TEMP_HIGH, outside_temp_init)

df_mixing = pd.DataFrame(mixing_temp_final)
df_mixing = df_mixing.set_index('Date')
print(df_mixing)

df_return = pd.DataFrame(return_temp_final)
df_return = df_return.set_index('Date')
print(df_return)

df_outside = pd.DataFrame(outside_temp_final)
df_outside = df_outside.set_index('Date')
print(df_outside)

df_mix_return = df_mixing.join(df_return)
df_final = df_mix_return.join(df_outside)
print(df_final)

df_final.plot()
plt.show()


df_final.to_csv('fc2_3_fake_data.csv')
print('DONE!!!')