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
ECON_SIG_LOW = 0
ECON_SIG_HIGH = 100
econ_damper_init = random.randint(ECON_SIG_LOW, ECON_SIG_HIGH)

CLG_VALVE_SIG_LOW = 0
CLG_VALVE_SIG_HIGH = 100
cooling_valve_init = random.randint(CLG_VALVE_SIG_LOW, CLG_VALVE_SIG_HIGH)

HTG_VALVE_SIG_LOW = 0
HTG_VALVE_SIG_HIGH = 100
heating_valve_init = random.randint(HTG_VALVE_SIG_LOW, HTG_VALVE_SIG_HIGH)


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


econ_damper_final = data_generator(
    'economizer_sig', ECON_SIG_LOW, ECON_SIG_HIGH, econ_damper_init)
cooling_valve_final = data_generator(
    'cooling_sig', CLG_VALVE_SIG_LOW, CLG_VALVE_SIG_HIGH, cooling_valve_init)
heating_valve_final = data_generator(
    'heating_sig', HTG_VALVE_SIG_LOW, HTG_VALVE_SIG_HIGH, heating_valve_init)



df_1 = pd.DataFrame(econ_damper_final)
df_1 = df_1.set_index('Date')
print(df_1)

df_2 = pd.DataFrame(cooling_valve_final)
df_2 = df_2.set_index('Date')
print(df_2)

df_3 = pd.DataFrame(heating_valve_final)
df_3 = df_3.set_index('Date')
print(df_3)

df_1_2 = df_1.join(df_2)
df_final = df_3.join(df_1_2)
print(df_final)

df_final.plot()
plt.show()

df_final.to_csv('fc4_fake_data3.csv')
print('DONE!!!')