import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeThreeReport:
    def __init__(self, config):
        self.mix_degf_err_thres = config['MIX_DEGF_ERR_THRES']
        self.return_degf_err_thres = config['RETURN_DEGF_ERR_THRES']
        self.outdoor_degf_err_thres = config['OUTDOOR_DEGF_ERR_THRES']
        self.mat_col = config['MAT_COL']
        self.rat_col = config['RAT_COL']
        self.oat_col = config['OAT_COL']
        self.supply_vfd_speed_col = config['SUPPLY_VFD_SPEED_COL']

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc3_flag"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle('Fault Conditions 3 Plot')

        ax1.plot(df.index, df[self.mat_col], color='r', label="Mix Temp")
        ax1.plot(df.index, df[self.rat_col], color='b', label="Return Temp")
        ax1.plot(df.index, df[self.oat_col], color='g', label="Out Temp")
        ax1.legend(loc='best')
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[output_col], label="Fault", color="k")
        ax2.set_xlabel('Date')
        ax2.set_ylabel('Fault Flags')
        ax2.legend(loc='best')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc3_flag"

        delta = df.index.to_series().diff()
        summary = {
            'total_days': round(delta.sum() / pd.Timedelta(days=1), 2),
            'total_hours': round(delta.sum() / pd.Timedelta(hours=1)),
            'hours_fc3_mode': round((delta * df[output_col]).sum() / pd.Timedelta(hours=1)),
            'percent_true': round(df[output_col].mean() * 100, 2),
            'percent_false': round((100 - round(df[output_col].mean() * 100, 2)), 2),
            'flag_true_mat': round(df[self.mat_col].where(df[output_col] == 1).mean(), 2),
            'flag_true_oat': round(df[self.oat_col].where(df[output_col] == 1).mean(), 2),
            'flag_true_rat': round(df[self.rat_col].where(df[output_col] == 1).mean(), 2),
            'hours_motor_runtime': round((delta * df[self.supply_vfd_speed_col].gt(.01).astype(int)).sum() / pd.Timedelta(hours=1), 2)
        }

        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc3_flag"

        df["hour_of_the_day_fc3"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc3.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 3 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc3_flag"):
        print("Fault Condition 3: Mix temperature too high; should be between outside and return air")

        self.create_plot(df, output_col)

        summary = self.summarize_fault_times(df, output_col)

        for key, value in summary.items():
            formatted_key = key.replace('_', ' ')
            print(f"{formatted_key}: {value}")
            sys.stdout.flush()

        fc_max_faults_found = df[output_col].max()
        print("Fault Flag Count: ", fc_max_faults_found)
        sys.stdout.flush()

        if fc_max_faults_found != 0:
            self.create_hist_plot(df, output_col)

            print("Mix Air Temp Mean When In Fault: ", summary['flag_true_mat'])
            print("Outside Air Temp Mean When In Fault: ", summary['flag_true_oat'])
            print("Return Temp Mean When In Fault: ", summary['flag_true_rat'])

            if summary['percent_true'] > 5.0:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is high, indicating potential issues with the mix temperature. Verify sensor calibration and investigate possible mechanical problems.'
                )
            else:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is low, indicating the system is likely functioning correctly.'
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
