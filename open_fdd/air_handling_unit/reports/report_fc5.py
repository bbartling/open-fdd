import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import sys


class FaultCodeFiveReport:
    """Class provides the definitions for Fault Condition 5 Report."""

    def __init__(self, config):
        self.mix_degf_err_thres = config['MIX_DEGF_ERR_THRES']
        self.supply_degf_err_thres = config['SUPPLY_DEGF_ERR_THRES']
        self.delta_t_supply_fan = config['DELTA_T_SUPPLY_FAN']
        self.mat_col = config['MAT_COL']
        self.sat_col = config['SAT_COL']
        self.heating_sig_col = config['HEATING_SIG_COL']
        self.supply_vfd_speed_col = config['SUPPLY_VFD_SPEED_COL']

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc5_flag"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle('Fault Conditions 5 Plot')

        ax1.plot(df.index, df[self.mat_col], color='g', label="Mix Temp")
        ax1.plot(df.index, df[self.sat_col], color='b', label="Supply Temp")
        ax1.legend(loc='best')
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[self.heating_sig_col], label="Htg Valve", color="r")
        ax2.set_xlabel('Date')
        ax2.set_ylabel('%')
        ax2.legend(loc='best')

        ax3.plot(df.index, df[output_col], label="Fault", color="k")
        ax3.set_xlabel('Date')
        ax3.set_ylabel('Fault Flags')
        ax3.legend(loc='best')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc5_flag"

        delta = df.index.to_series().diff()
        summary = {
            'total_days': round(delta.sum() / pd.Timedelta(days=1), 2),
            'total_hours': round(delta.sum() / pd.Timedelta(hours=1)),
            'hours_fc5_mode': round((delta * df[output_col]).sum() / pd.Timedelta(hours=1)),
            'percent_true': round(df[output_col].mean() * 100, 2),
            'percent_false': round((100 - round(df[output_col].mean() * 100, 2)), 2),
            'flag_true_mat': round(df[self.mat_col].where(df[output_col] == 1).mean(), 2),
            'flag_true_sat': round(df[self.sat_col].where(df[output_col] == 1).mean(), 2),
            'hours_motor_runtime': round((delta * df[self.supply_vfd_speed_col].gt(.01).astype(int)).sum() / pd.Timedelta(hours=1), 2)
        }

        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc5_flag"

        # Calculate dataset statistics
        df["hour_of_the_day_fc5"] = df.index.hour.where(df[output_col] == 1)

        # Make hist plots fc5
        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc5.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 5 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc5_flag"):
        # Display report content in IPython
        print("Fault Condition 5: Supply air temperature too low; should be higher than mix air")

        # Display plot
        self.create_plot(df, output_col)

        # Display summary statistics
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

            flag_true_mat = round(
                df[self.mat_col].where(df[output_col] == 1).mean(), 2
            )
            print("Mix Air Temp Mean When In Fault: ", flag_true_mat)

            flag_true_sat = round(
                df[self.sat_col].where(df[output_col] == 1).mean(), 2
            )
            print("Supply Air Temp Mean When In Fault: ", flag_true_sat)

            sys.stdout.flush()

            if summary['percent_true'] > 5.0:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is high indicating the AHU temperature sensors for either the supply or mix temperature are out of calibration. Verify the mixing temperature sensor is not a probe type sensor but a long averaging type sensor that is installed properly inside the AHU mixing chamber to get a good solid true reading of the actual air mixing temperature. Poor duct design may also contribute to not having good air mixing, to troubleshoot install data loggers inside the mixing chamber or take measurements when the AHU is running of different locations in the mixing chamber to spot where better air blending needs to take place.'
                )
            else:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is low indicating the AHU temperature sensors are within calibration.'
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
