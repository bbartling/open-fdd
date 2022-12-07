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

MIX_TEMP_LOW = 45
MIX_TEMP_HIGH = 70
mix_temp_init = random.randint(MIX_TEMP_LOW, MIX_TEMP_HIGH)

final_mixing = []
mix_temp_lv = None


# iterating through timestamp range
for i in range(len(timestamp_range)):

    stamp_and_temp = {}

    if mix_temp_lv == None:
        mix_temp = mix_temp_init

    else:
        rander = random.random()
        if rander > .5:
            rander = 1
        else:
            rander = -1
        mix_temp = mix_temp + rander

    if mix_temp > MIX_TEMP_HIGH:
        mix_temp -= 1

    if mix_temp < MIX_TEMP_LOW:
        mix_temp += 1

    stamp_and_temp['Date'] = timestamp_range[i]
    stamp_and_temp['mixing_temp'] = mix_temp

    final_mixing.append(stamp_and_temp)
    mix_temp_lv = mix_temp
    

df = pd.DataFrame(final_mixing)
df = df.set_index('Date')
print(df)

df.plot()
plt.show()



