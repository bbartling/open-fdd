import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeElevenReport:
    """Class provides the definitions for Fault Condition 11 Report."""

    def __init__(self, config):
        self.sat_setpoint_col = config['SAT_SETPOINT_COL']
        self.oat_col = config['OAT_COL']
        self.cooling_sig_col = config['COOLING_SIG_COL']
        self.economizer_sig_col = config['ECONOMIZER_SIG_COL']
        self.supply_vfd_speed_col = config['SUPPLY_VFD_SPEED_COL']

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc11_flag"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle('Fault Conditions 11 Plot')

        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATSP")
        ax1.plot(df.index, df[self.oat_col], label="OAT")
        ax1.legend(loc='best')
        ax1.set_ylabel('AHU Temps °F')

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.plot(df.index, df[self.economizer_sig_col], label="AHU Dpr Cmd", color="g")
        ax2.legend(loc='best')
        ax2.set_ylabel('%')

        ax3.plot(df.index, df[output_col], label="Fault", color="k")
        ax3.set_xlabel('Date')
        ax3.set_ylabel('Fault Flags')
        ax3.legend(loc='best')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc11_flag"

        delta = df.index.to_series().diff()
        summary = {
            'total_days': round(delta.sum() / pd.Timedelta(days=1), 2),
            'total_hours': round(delta.sum() / pd.Timedelta(hours=1)),
            'hours_fc11_mode': round((delta * df[output_col]).sum() / pd.Timedelta(hours=1)),
            'percent_true': round(df[output_col].mean() * 100, 2),
            'percent_false': round((100 - round(df[output_col].mean() * 100, 2)), 2),
            'flag_true_oat': round(df[self.oat_col].where(df[output_col] == 1).mean(), 2),
            'flag_true_sat_sp': round(df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2),
            'hours_motor_runtime': round((delta * df[self.supply_vfd_speed_col].gt(.01).astype(int)).sum() / pd.Timedelta(hours=1), 2)
        }

        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc11_flag"

        df["hour_of_the_day_fc11"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc11.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 11 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc11_flag"):
        print("Fault Condition 11: Outside air temperature too low for 100% outside air cooling in economizer mode")

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

            flag_true_oat = round(df[self.oat_col].where(df[output_col] == 1).mean(), 2)
            print("Outside Air Temp Mean When In Fault: ", flag_true_oat)

            flag_true_sat_sp = round(df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2)
            print("Supply Air Temp Setpoint Mean When In Fault: ", flag_true_sat_sp)

            sys.stdout.flush()

            if summary['percent_true'] > 5.0:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is high, indicating temperature sensor error or the heating coil could be leaking, potentially creating simultaneous heating/cooling scenarios. Visually verify damper operation, and consider tuning the BAS programming for proper AHU operation.'
                )
            else:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is low, indicating the AHU components are within calibration for this fault equation.'
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
