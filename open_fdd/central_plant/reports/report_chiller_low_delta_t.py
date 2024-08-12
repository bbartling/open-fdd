import matplotlib.pyplot as plt
import pandas as pd
import sys

class FaultCodeLowDeltaTReport:
    """Class provides the definitions for Low Delta T Fault Condition Report in Chiller Plant."""

    def __init__(self, config):
        self.chw_supply_temp_col = config['CHW_SUPPLY_TEMP_COL']
        self.chw_return_temp_col = config['CHW_RETURN_TEMP_COL']
        self.chw_flow_rate_col = config['CHW_FLOW_RATE_COL']

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "low_delta_t_flag"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle('Low Delta T Fault Condition Plot')

        ax1.plot(df.index, df[self.chw_supply_temp_col], label="CHW Supply Temp", color="b")
        ax1.plot(df.index, df[self.chw_return_temp_col], label="CHW Return Temp", color="r")
        ax1.legend(loc='best')
        ax1.set_ylabel("Temperature (°F)")

        ax2.plot(df.index, df["delta_t"], label="Delta T", color="g")
        ax2.legend(loc='best')
        ax2.set_ylabel("Delta T (°F)")

        ax3.plot(df.index, df[output_col], label="Fault Flag", color="k")
        ax3.set_xlabel('Date')
        ax3.set_ylabel('Fault Flags')
        ax3.legend(loc='best')

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "low_delta_t_flag"

        delta = df.index.to_series().diff()
        summary = {
            'total_days': round(delta.sum() / pd.Timedelta(days=1), 2),
            'total_hours': round(delta.sum() / pd.Timedelta(hours=1)),
            'hours_low_delta_t': round((delta * df[output_col]).sum() / pd.Timedelta(hours=1)),
            'percent_true': round(df[output_col].mean() * 100, 2),
            'percent_false': round((100 - round(df[output_col].mean() * 100, 2)), 2),
            'flag_true_delta_t': round(df["delta_t"].where(df[output_col] == 1).mean(), 2),
            'hours_motor_runtime': round((delta * df[self.chw_flow_rate_col].gt(.01).astype(int)).sum() / pd.Timedelta(hours=1), 2)
        }

        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "low_delta_t_flag"

        df["hour_of_the_day_low_delta_t"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_low_delta_t.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Low Delta T Fault is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "low_delta_t_flag"):
        print("Low Delta T Fault Condition: Chiller Plant Efficiency Reduction")

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

            print("Delta T Mean When In Fault: ", summary['flag_true_delta_t'])

            if summary['percent_true'] > 5.0:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is high, indicating potential issues with chiller efficiency. Investigate possible mechanical problems, sensor calibration, or system design issues.'
                )
            else:
                print(
                    'The percent True metric that represents the amount of time for when the fault flag is True is low, indicating the system is likely functioning correctly.'
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
