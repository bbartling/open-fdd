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

FAN_SPEED_LOW = 10
FAN_SPEED_HIGH = 100
fan_speed_init = random.randint(FAN_SPEED_LOW, FAN_SPEED_HIGH)

DUCT_STATIC_LOW = .01
DUCT_STATIC_HIGH = 2
duct_static_init = random.uniform(DUCT_STATIC_LOW, DUCT_STATIC_HIGH)


def data_generator(sensor_name, SENSOR_LOW, SENSOR_HIGH, sensor_init, floats=False):
    final_rand_data = []
    temp_lv = None
    global timestamp_range
    # iterating through timestamp range
    for i in range(len(timestamp_range)):
        stamp_and_temp = {}
        if temp_lv == None:
            _temp = sensor_init
        else:
            # generate rand float between 0 and 1
            rander = random.random()
            if not floats: # generate ints
                if rander > .5:
                    rander = 1
                else:
                    rander = -1
            else: # generate floats
                if rander > .5:
                    rander = .1
                else:
                    rander = -.1                
            _temp = _temp + rander
        if _temp > SENSOR_HIGH:
            _temp -= 1
        if _temp < SENSOR_LOW:
            _temp += 1
        stamp_and_temp['Date'] = timestamp_range[i]
        stamp_and_temp[str(sensor_name)] = _temp
        final_rand_data.append(stamp_and_temp)
        temp_lv = _temp
    return final_rand_data


duct_static_final = data_generator(
    'duct_static', DUCT_STATIC_LOW, DUCT_STATIC_HIGH, duct_static_init, floats=True)
fan_speed_final = data_generator(
    'supply_vfd_speed', FAN_SPEED_LOW, FAN_SPEED_HIGH, fan_speed_init)


df_one = pd.DataFrame(duct_static_final)
df_one = df_one.set_index('Date')
print(df_one)

df_two = pd.DataFrame(fan_speed_final)
df_two = df_two.set_index('Date')
print(df_two)

df_final = df_one.join(df_two)
print(df_final)

df_final.plot()
plt.show()

data_file_name = 'fc1_fake_data3'
df_final.to_csv(f'{data_file_name}.csv')
print('DONE!!! saved: ',data_file_name)