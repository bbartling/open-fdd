import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


df = pd.read_csv('https://raw.githubusercontent.com/bbartling/Data/master/hvac_random_fake_data/test2.csv',
             index_col='Date')
print(df)


fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25,8))
plt.title('Fault Conditions 2 and 3 Plots')
 
plot1a, = ax1.plot(df.index, df.mat, color='r') # red
plot1b, = ax1.plot(df.index, df.rat, color='b') # blue
plot1c, = ax1.plot(df.index, df.oat, color='g') # green
ax1.set_ylabel('AHU Temp Sensors')

ax2.plot(df.index, df.fc2_flag, color='c') # cyan
ax2.plot(df.index, df.fc3_flag, color='m') # purple
ax2.set_xlabel('Date')
ax2.set_ylabel('Fault Flags')


red_patch = mpatches.Patch(color='red', label='MAT')
blue_patch = mpatches.Patch(color='blue', label='RAT')
green_patch = mpatches.Patch(color='green', label='OAT')
cyan_patch = mpatches.Patch(color='cyan', label='fc2_flag')
purple_patch = mpatches.Patch(color='purple', label='fc3_flag')
plt.legend(handles=[red_patch,blue_patch,green_patch,cyan_patch,purple_patch])

# defining display layout
plt.tight_layout()

# show plot
plt.show()
